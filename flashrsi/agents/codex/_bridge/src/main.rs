#![recursion_limit = "256"]

//! A transport boundary around the unchanged, pinned Codex core libraries.
//! No CLI, app-server, SDK, or replacement agent loop is linked by this executable.

mod extensions;
mod host_requests;
mod models_refresh_worker;

use std::io::{self, BufWriter, Write};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use anyhow::{Context, Result};
use codex_analytics::AnalyticsEventsClient;
use codex_arg0::Arg0DispatchPaths;
use codex_config::ConfigLoadOptions;
use codex_core::config::{
    ConfigBuilder, ConfigOverrides, bootstrap_auth_config, load_config_toml_with_layer_stack,
};
use codex_core::{SleepFuture, StartThreadOptions, ThreadManager, TimeFuture, TimeProvider};
use codex_exec_server::{EnvironmentManager, ExecServerRuntimePaths};
use codex_extension_api::{ExtensionEventSink, ExtensionWarning};
use codex_home::CodexHomeUserInstructionsProvider;
use codex_login::AuthManager;
use codex_protocol::ThreadId;
use codex_protocol::config_types::{ApprovalsReviewer, SandboxMode, TrustLevel};
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::{
    AskForApproval, Event, EventMsg, Op, SessionSource, ThreadSettingsOverrides, ThreadSource,
    TokenUsage, TurnEnvironmentSelections, WarningEvent,
};
use codex_protocol::user_input::UserInput;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::{Deserialize, Serialize};
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::task::JoinSet;
use tracing_subscriber::EnvFilter;

const SOURCE_REVISION: &str = "be6e8eac029b183056b7e4402879f15d2c85f61b";

struct ExecTimeProvider;

impl TimeProvider for ExecTimeProvider {
    fn current_time(&self, _thread_id: ThreadId) -> TimeFuture<'_> {
        // app-server/src/current_time.rs maps the fixed exec host's -32000
        // rejection (exec/src/lib.rs) to this exact error. Keep the provider
        // available at thread/start; only an actual external-clock read fails.
        Box::pin(async {
            anyhow::bail!(
                "current-time request failed: code=-32000 message=external current time is not supported in exec mode"
            )
        })
    }

    fn sleep(&self, thread_id: ThreadId, _duration: Duration) -> SleepFuture<'_> {
        // The upstream external sleep first reads that same rejected clock.
        let current_time = self.current_time(thread_id);
        Box::pin(async move { current_time.await.map(|_| ()) })
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    prompt: String,
    cwd: PathBuf,
    codex_home: PathBuf,
    model: Option<String>,
    default_zsh_path: Option<PathBuf>,
    #[serde(default)]
    overrides: Vec<(String, String)>,
    #[serde(default = "default_sandbox")]
    sandbox: String,
    #[serde(default)]
    bypass_hook_trust: bool,
}

fn default_sandbox() -> String {
    "workspace-write".to_string()
}

pub struct Output(Mutex<BufWriter<io::Stdout>>);

impl Output {
    fn new() -> Self {
        Self(Mutex::new(BufWriter::new(io::stdout())))
    }

    fn write<T: Serialize>(&self, value: &T) -> Result<()> {
        let mut writer = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("output lock poisoned"))?;
        serde_json::to_writer(&mut *writer, value)?;
        writer.write_all(b"\n")?;
        writer.flush()?;
        Ok(())
    }
}

impl ExtensionEventSink for Output {
    fn emit(&self, event: Event) {
        if let Err(error) = self.write(&event) {
            tracing::error!(%error, "failed to forward extension event");
        }
    }

    fn emit_warning(&self, warning: ExtensionWarning) {
        // Keep thread targeting that is carried outside EventMsg::Warning upstream.
        let event = json!({
            "type": "flashrsi.core.extension_warning",
            "thread_id": warning.thread_id,
            "turn_id": warning.turn_id,
            "message": warning.message,
        });
        if let Err(error) = self.write(&event) {
            tracing::error!(%error, "failed to forward extension warning");
        }
    }
}

fn main() -> Result<()> {
    // Native tools re-exec this binary for apply_patch, filesystem, exec and sandbox
    // helpers. Dispatch before reading JSON or constructing the Tokio runtime.
    codex_arg0::arg0_dispatch_or_else(|paths| async move {
        let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| {
            EnvFilter::new("warn,opentelemetry_sdk=off,opentelemetry_otlp=off")
        });
        let _ = tracing_subscriber::fmt()
            .with_env_filter(filter)
            .with_writer(io::stderr)
            .with_ansi(false)
            .try_init();
        let output = Arc::new(Output::new());
        match run(paths, output.clone()).await {
            Ok(()) => Ok(()),
            Err(error) => {
                output.write(&json!({
                    "type": "flashrsi.core.completed",
                    "status": "error",
                    "output": "",
                    "usage": {},
                    "error_message": format!("{error:#}"),
                }))?;
                Err(error)
            }
        }
    })
}

async fn run(paths: Arg0DispatchPaths, output: Arc<Output>) -> Result<()> {
    let mut line = String::new();
    let read = tokio::io::BufReader::new(tokio::io::stdin())
        .read_line(&mut line)
        .await?;
    anyhow::ensure!(read > 0, "expected one JSON request on stdin");
    let request: Request = serde_json::from_str(&line).context("invalid core request")?;
    let sandbox_mode = match request.sandbox.as_str() {
        "read-only" => SandboxMode::ReadOnly,
        "workspace-write" => SandboxMode::WorkspaceWrite,
        "danger-full-access" => SandboxMode::DangerFullAccess,
        value => anyhow::bail!("unsupported sandbox mode: {value}"),
    };
    let overrides = request
        .overrides
        .into_iter()
        .map(|(key, value)| {
            // A TOML document wrapper permits scalars, arrays and inline tables alike.
            let document: toml::Table = format!("value = {value}")
                .parse()
                .with_context(|| format!("invalid TOML override for {key}"))?;
            let value = document
                .get("value")
                .cloned()
                .context("missing override value")?;
            Ok((key, value))
        })
        .collect::<Result<Vec<_>>>()?;
    let _ = codex_login::default_client::set_default_originator("codex_exec".to_string());
    let cwd = AbsolutePathBuf::from_absolute_path(&request.cwd)?;
    let bootstrap = load_config_toml_with_layer_stack(
        &request.codex_home,
        Some(&cwd),
        overrides.clone(),
        ConfigLoadOptions {
            strict_config: true,
            ..Default::default()
        },
    )
    .await?;
    let cloud_config_bundle = codex_cloud_config::cloud_config_bundle_loader_for_storage(
        bootstrap_auth_config(&request.codex_home, &bootstrap)?,
        false,
    )
    .await;
    let config_builder = ConfigBuilder::default()
        .codex_home(request.codex_home.clone())
        .cli_overrides(overrides.clone())
        .cloud_config_bundle(cloud_config_bundle)
        .strict_config(true);
    let harness_overrides = ConfigOverrides {
        model: request.model,
        cwd: Some(request.cwd),
        approval_policy: Some(AskForApproval::Never),
        sandbox_mode: Some(sandbox_mode),
        ephemeral: Some(true),
        psp: Some(false),
        bypass_hook_trust: request.bypass_hook_trust.then_some(true),
        codex_self_exe: paths.codex_self_exe.clone(),
        codex_linux_sandbox_exe: paths.codex_linux_sandbox_exe.clone(),
        main_execve_wrapper_exe: paths.main_execve_wrapper_exe,
        default_zsh_path: request
            .default_zsh_path
            .map(AbsolutePathBuf::from_absolute_path)
            .transpose()?,
        ..Default::default()
    };
    // Match exec's automatic reviewer handling without replacing its policy logic.
    let build = |overrides| config_builder.clone().harness_overrides(overrides).build();
    let build_without_headless_approval = || {
        build(ConfigOverrides {
            approval_policy: None,
            ..harness_overrides.clone()
        })
    };
    let mut config = match build(harness_overrides.clone()).await {
        Ok(config) if config.approvals_reviewer == ApprovalsReviewer::AutoReview => {
            build_without_headless_approval().await?
        }
        Ok(config) => config,
        Err(headless_error) => match build_without_headless_approval().await {
            Ok(config) if config.approvals_reviewer == ApprovalsReviewer::AutoReview => config,
            Ok(_) | Err(_) => return Err(headless_error.into()),
        },
    };
    match codex_core::check_execpolicy_for_warnings(&config.config_layer_stack).await {
        Ok(None) => {}
        Ok(Some(error)) => anyhow::bail!("Error loading rules: {error}"),
        Err(error) => return Err(error.into()),
    }
    codex_login::default_client::set_default_client_residency_requirement(
        config.enforce_residency.value(),
    );
    // app-server performs this same native project-trust reload at thread/start.
    // FlashRSI normally supplies explicit untrusted task roots, leaving it inactive.
    let effective_profile = config.permissions.effective_permission_profile();
    let effective_trust = match &effective_profile {
        PermissionProfile::Disabled | PermissionProfile::External { .. } => true,
        PermissionProfile::Managed { .. } => effective_profile
            .file_system_sandbox_policy()
            .can_write_path_with_cwd(config.cwd.as_path(), config.cwd.as_path()),
    };
    if config.active_project.trust_level.is_none()
        && (matches!(
            sandbox_mode,
            SandboxMode::WorkspaceWrite | SandboxMode::DangerFullAccess
        ) || effective_trust)
    {
        let trust_target = codex_git_utils::resolve_root_git_project_for_trust(
            codex_exec_server::LOCAL_FS.as_ref(),
            &config.cwd,
        )
        .await
        .unwrap_or_else(|| config.cwd.clone());
        let mut builder = config_builder.clone();
        if let Err(error) = codex_core::config::set_project_trust_level(
            &request.codex_home,
            trust_target.as_path(),
            TrustLevel::Trusted,
        ) {
            tracing::warn!(%error, "failed to persist native project trust; using in-memory trust");
            let projects = toml::Value::Table(toml::map::Map::from_iter([(
                codex_config::loader::project_trust_key(trust_target.as_path()),
                toml::Value::Table(toml::map::Map::from_iter([(
                    "trust_level".to_string(),
                    toml::Value::String("trusted".to_string()),
                )])),
            )]));
            let mut overrides = overrides;
            overrides.push(("projects".to_string(), projects));
            builder = builder.cli_overrides(overrides);
        }
        config = builder
            .harness_overrides(ConfigOverrides {
                approval_policy: Some(config.permissions.approval_policy.value()),
                ..harness_overrides
            })
            .build()
            .await?;
    }
    config.auth_config().validate()?;
    let auth_manager = AuthManager::shared_from_config(&config, true).await;
    codex_login::enforce_login_restrictions(&config.auth_config()).await?;
    // exec forwards these nonfatal configuration warnings through app-server's
    // ConfigWarning presentation. Preserve their original text as native events.
    for warning in &config.startup_warnings {
        output.write(&Event {
            id: String::new(),
            msg: EventMsg::Warning(WarningEvent {
                message: warning.clone(),
            }),
        })?;
    }
    let runtime_paths = ExecServerRuntimePaths::from_optional_paths(
        paths.codex_self_exe,
        paths.codex_linux_sandbox_exe,
    )?;
    let environment_manager = Arc::new(
        EnvironmentManager::from_codex_home(
            &config.codex_home,
            Some(runtime_paths),
            config.http_client_factory(),
        )
        .await?,
    );
    let otel = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        codex_core::otel_init::build_provider(
            &config,
            env!("CARGO_PKG_VERSION"),
            Some("codex_exec"),
            true,
        )
    })) {
        Ok(Ok(otel)) => otel,
        Ok(Err(error)) => {
            tracing::warn!(%error, "Could not create otel exporter");
            None
        }
        Err(_) => {
            tracing::warn!("Could not create otel exporter: panicked during initialization");
            None
        }
    };
    codex_core::otel_init::record_process_start(otel.as_ref(), "codex_exec");
    codex_core::otel_init::install_sqlite_telemetry(otel.as_ref(), "codex_exec");
    let state_db = codex_core::init_state_db(&config).await;
    let analytics = AnalyticsEventsClient::new(
        auth_manager.clone(),
        config.chatgpt_base_url.trim_end_matches('/').to_string(),
        config.analytics_enabled,
    );
    let thread_store = codex_core::thread_store_from_config(&config, state_db.clone());
    let installation_id = codex_core::resolve_installation_id(&config.codex_home).await?;
    let manager = Arc::new_cyclic(|weak| {
        ThreadManager::new(
            &config,
            auth_manager.clone(),
            codex_core::build_models_manager(&config, auth_manager.clone()),
            codex_core::CodexAppsToolsCache::default(),
            SessionSource::Exec,
            environment_manager.clone(),
            extensions::register(
                &config,
                auth_manager.clone(),
                state_db.clone(),
                analytics.clone(),
                weak.clone(),
                environment_manager.clone(),
                output.clone(),
            ),
            Arc::new(CodexHomeUserInstructionsProvider::new(
                config.codex_home.clone(),
            )),
            Some(analytics.clone()),
            thread_store.clone(),
            codex_core::local_agent_graph_store_from_state_db(state_db.as_ref()),
            installation_id.clone(),
            None,
            Some(Arc::new(ExecTimeProvider)),
        )
    });
    // These native lifecycle hooks live in app-server's composition layer at
    // the pinned revision; removing its transport must not remove their work.
    let models_refresh_worker =
        models_refresh_worker::spawn(&manager.get_models_manager(), config.http_client_factory());
    manager
        .plugins_manager()
        .set_analytics_events_client(analytics.clone());
    let weak_manager = Arc::downgrade(&manager);
    manager
        .plugins_manager()
        .maybe_start_plugin_startup_tasks_for_config(
            &config.plugins_config_input(),
            auth_manager,
            Some(Arc::new(move |_change| {
                // app-server/src/effective_plugin_change.rs refreshes the same
                // consumers after background plugin materialization. Its later
                // account-backed hook-trust RPC branch requires native login,
                // which the API-key-only FlashRSI adapter does not accept.
                let Some(manager) = weak_manager.upgrade() else {
                    return;
                };
                manager.plugins_manager().clear_cache();
                manager.skills_service().clear_cache();
                tokio::spawn(async move {
                    manager.invalidate_mcp_runtimes().await;
                });
            })),
        );
    let mut listeners = JoinSet::new();
    let result = run_turn(
        &manager,
        config,
        request.prompt,
        output.clone(),
        &mut listeners,
    )
    .await;
    let report = manager
        .shutdown_all_threads_bounded(Duration::from_secs(10))
        .await;
    if !report.submit_failed.is_empty() || !report.timed_out.is_empty() {
        tracing::warn!(?report, "core threads did not all shut down cleanly");
    }
    models_refresh_worker.shutdown();
    analytics.flush().await;
    listeners.abort_all();
    while listeners.join_next().await.is_some() {}
    // Keep native telemetry alive until every session and extension has stopped.
    drop(manager);
    drop(otel);
    result
}

async fn run_turn(
    manager: &Arc<ThreadManager>,
    config: codex_core::config::Config,
    prompt: String,
    output: Arc<Output>,
    listeners: &mut JoinSet<()>,
) -> Result<()> {
    let environments = manager.default_environment_selections(&config.cwd, &config.workspace_roots);
    let thread_settings = ThreadSettingsOverrides {
        environments: Some(TurnEnvironmentSelections::new(
            config.cwd.clone(),
            environments.clone(),
        )),
        approval_policy: Some(config.permissions.approval_policy.value()),
        effort: config.model_reasoning_effort.clone().map(Some),
        ..Default::default()
    };
    let started = manager
        .start_thread(StartThreadOptions {
            thread_source: Some(ThreadSource::User),
            environments: Some(environments),
            ..StartThreadOptions::new(config)
        })
        .await?;
    // Native exec identifies its client at thread/start; hooks and subagents
    // receive the same client context through the core session.
    started
        .thread
        .set_app_server_client_info(
            Some("codex_exec".to_string()),
            Some(env!("CARGO_PKG_VERSION").to_string()),
            false,
        )
        .await?;
    output.write(&json!({
        "type": "flashrsi.core.started",
        "thread_id": started.thread_id.to_string(),
        "version": env!("CARGO_PKG_VERSION"),
        "source_revision": SOURCE_REVISION,
        "session_configured": started.session_configured,
    }))?;
    // Core subagents have their own event queues. Native exec's app-server
    // attaches listeners to them so their host requests are answered as well.
    let mut created = manager.subscribe_thread_created();
    let weak_manager = Arc::downgrade(manager);
    let subagent_output = output.clone();
    listeners.spawn(async move {
        let mut agents = JoinSet::new();
        loop {
            let thread_id = match created.recv().await {
                Ok(thread_id) => thread_id,
                Err(tokio::sync::broadcast::error::RecvError::Lagged(skipped)) => {
                    tracing::warn!(skipped, "subagent creation listener lagged");
                    continue;
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
            };
            let Some(manager) = weak_manager.upgrade() else {
                break;
            };
            let thread = match manager.get_thread(thread_id).await {
                Ok(thread) => thread,
                Err(error) => {
                    tracing::warn!(%error, %thread_id, "cannot attach subagent listener");
                    continue;
                }
            };
            let output = subagent_output.clone();
            agents.spawn(async move {
                loop {
                    let event = match thread.next_event().await {
                        Ok(event) => event,
                        Err(error) => {
                            tracing::warn!(%error, %thread_id, "subagent event stream ended");
                            break;
                        }
                    };
                    let _ = output.write(&json!({
                        "type": "flashrsi.core.subagent_event",
                        "thread_id": thread_id,
                        "event": event,
                    }));
                    if let Err(error) = host_requests::respond(&thread, &event).await {
                        tracing::warn!(%error, %thread_id, "subagent host response failed");
                    }
                    if matches!(event.msg, EventMsg::ShutdownComplete) {
                        break;
                    }
                }
            });
            while agents.try_join_next().is_some() {}
        }
    });
    let turn_id = started
        .thread
        .submit_user_input_with_client_user_message_id(
            Op::UserInput {
                items: vec![UserInput::Text {
                    text: prompt,
                    text_elements: Vec::new(),
                }],
                final_output_json_schema: None,
                responsesapi_client_metadata: None,
                additional_context: Default::default(),
                thread_settings,
            },
            None,
            None,
        )
        .await?;
    let mut usage = TokenUsage::default();
    let signal = tokio::signal::ctrl_c();
    tokio::pin!(signal);
    let mut interrupted = false;
    let (final_output, error_message) = loop {
        let event = tokio::select! {
            event = started.thread.next_event() => event?,
            signal_result = &mut signal, if !interrupted => {
                signal_result?;
                interrupted = true;
                started.thread.submit(Op::Interrupt).await?;
                continue;
            }
        };
        output.write(&event)?;
        host_requests::respond(&started.thread, &event).await?;
        match event.msg {
            EventMsg::TokenCount(count) => {
                if let Some(info) = count.info {
                    usage = info.total_token_usage;
                }
            }
            EventMsg::TurnComplete(complete) => {
                // The terminal event is authoritative; retries may have emitted Error.
                break (
                    complete.last_agent_message.unwrap_or_default(),
                    complete.error.map(|error| error.message),
                );
            }
            EventMsg::TurnAborted(aborted) => {
                break (
                    String::new(),
                    Some(format!("turn aborted: {:?}", aborted.reason)),
                );
            }
            EventMsg::ShutdownComplete => {
                break (
                    String::new(),
                    Some("core shut down before turn completion".to_string()),
                );
            }
            _ => {}
        }
    };
    output.write(&json!({
        "type": "flashrsi.core.completed",
        "thread_id": started.thread_id.to_string(),
        "turn_id": turn_id,
        "status": if error_message.is_none() { "finished" } else { "error" },
        "output": final_output,
        "usage": usage,
        "error_message": error_message,
    }))?;
    Ok(())
}
