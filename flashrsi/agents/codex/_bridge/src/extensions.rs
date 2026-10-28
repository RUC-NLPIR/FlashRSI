//! Native registration order from app-server/src/extensions.rs at the locked revision.
//! Only the transport-facing event sink and guardian spawner are supplied by this host.

use std::sync::{Arc, Weak};

use codex_analytics::AnalyticsEventsClient;
use codex_core::config::Config;
use codex_core::{NewThread, StartThreadOptions, StateDbHandle, ThreadManager};
use codex_exec_server::EnvironmentManager;
use codex_extension_api::{AgentSpawnFuture, ExtensionRegistry, ExtensionRegistryBuilder};
use codex_features::Feature;
use codex_goal_extension::GoalService;
use codex_login::AuthManager;
use codex_protocol::{ThreadId, error::CodexErr};

use crate::Output;

pub fn register(
    config: &Config,
    auth_manager: Arc<AuthManager>,
    state_db: Option<StateDbHandle>,
    analytics_events_client: AnalyticsEventsClient,
    thread_manager: Weak<ThreadManager>,
    environment_manager: Arc<EnvironmentManager>,
    output: Arc<Output>,
) -> Arc<ExtensionRegistry<Config>> {
    let mut builder = ExtensionRegistryBuilder::<Config>::with_event_sink(output);
    if let Some(state_db) = state_db {
        codex_goal_extension::install_with_backend(
            &mut builder,
            state_db,
            analytics_events_client,
            codex_otel::global(),
            thread_manager.clone(),
            Arc::new(GoalService::new()),
            |config: &Config| config.features.enabled(Feature::Goals),
        );
    }
    codex_git_attribution::install(
        &mut builder,
        auth_manager.clone(),
        config.chatgpt_base_url.clone(),
        config.http_client_factory(),
    );
    let guardian_spawner = move |forked_from_thread_id: ThreadId,
                                 options: StartThreadOptions|
          -> AgentSpawnFuture<'static, NewThread, CodexErr> {
        let thread_manager = thread_manager.clone();
        Box::pin(async move {
            let thread_manager = thread_manager.upgrade().ok_or_else(|| {
                CodexErr::UnsupportedOperation("thread manager dropped".to_string())
            })?;
            thread_manager
                .spawn_subagent(forked_from_thread_id, options)
                .await
        })
    };
    codex_guardian::install(&mut builder, guardian_spawner);
    codex_memories_extension::install(&mut builder, codex_otel::global());
    codex_mcp_extension::install(&mut builder);
    codex_mcp_extension::install_executor_plugins(&mut builder, environment_manager.clone());
    codex_web_search_extension::install(&mut builder, auth_manager.clone());
    codex_image_generation_extension::install(&mut builder, auth_manager, |config: &Config| {
        Some(config.codex_home.clone())
    });
    let executor_skill_provider = Arc::new(
        codex_skills_extension::ExecutorSkillProvider::new_with_restriction_product(
            environment_manager,
            codex_protocol::protocol::SessionSource::Exec.restriction_product(),
        ),
    );
    let skill_providers = codex_skills_extension::SkillProviders::new()
        .with_executor_provider(executor_skill_provider)
        .with_orchestrator_provider(Arc::new(
            codex_skills_extension::OrchestratorSkillProvider::new(),
        ))
        .with_host_provider(Arc::new(codex_skills_extension::HostSkillProvider::new()));
    codex_skills_extension::install_with_providers_and_metrics(
        &mut builder,
        skill_providers,
        codex_otel::global(),
        |config: &Config| codex_skills_extension::SkillsExtensionConfig {
            include_instructions: config.include_skill_instructions,
            bundled_skills_enabled: config.bundled_skills_enabled(),
            orchestrator_skills_enabled: config.orchestrator_skills_enabled,
            shadow_selection_enabled: config.features.enabled(Feature::SkillSearch),
        },
    );
    Arc::new(builder.build())
}
