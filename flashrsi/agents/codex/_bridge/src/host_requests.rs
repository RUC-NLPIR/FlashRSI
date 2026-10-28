//! Headless responses made by the native exec host, after its app-server mapping.
//! The core keeps ownership of tool execution and of every waiting continuation.

use anyhow::Result;
use codex_core::CodexThread;
use codex_protocol::approvals::ElicitationAction;
use codex_protocol::dynamic_tools::{DynamicToolCallOutputContentItem, DynamicToolResponse};
use codex_protocol::protocol::{Event, EventMsg, Op, ReviewDecision};
use codex_protocol::request_permissions::{PermissionGrantScope, RequestPermissionsResponse};
use codex_protocol::request_user_input::RequestUserInputResponse;

pub async fn respond(thread: &CodexThread, event: &Event) -> Result<()> {
    let response = match &event.msg {
        // codex exec explicitly cancels MCP elicitations, including in subagents.
        EventMsg::ElicitationRequest(request) => Op::ResolveElicitation {
            server_name: request.server_name.clone(),
            request_id: request.id.clone(),
            decision: ElicitationAction::Cancel,
            content: None,
            meta: None,
        },
        // These are the native app-server fallback values after exec rejects its
        // unsupported interactive request. Preserve their exact core payloads.
        EventMsg::RequestUserInput(request) => Op::UserInputAnswer {
            id: if request.turn_id.is_empty() {
                event.id.clone()
            } else {
                request.turn_id.clone()
            },
            response: RequestUserInputResponse {
                answers: Default::default(),
            },
        },
        EventMsg::RequestPermissions(request) => Op::RequestPermissionsResponse {
            id: request.call_id.clone(),
            response: RequestPermissionsResponse {
                permissions: Default::default(),
                scope: PermissionGrantScope::Turn,
                strict_auto_review: false,
            },
        },
        EventMsg::ExecApprovalRequest(request) => Op::ExecApproval {
            id: request
                .approval_id
                .clone()
                .unwrap_or_else(|| request.call_id.clone()),
            turn_id: Some(request.turn_id.clone()),
            decision: ReviewDecision::denied("approval request failed"),
        },
        EventMsg::ApplyPatchApprovalRequest(request) => Op::PatchApproval {
            id: request.call_id.clone(),
            decision: ReviewDecision::denied("approval request failed"),
        },
        EventMsg::DynamicToolCallRequest(request) => Op::DynamicToolResponse {
            id: request.call_id.clone(),
            response: DynamicToolResponse {
                content_items: vec![DynamicToolCallOutputContentItem::InputText {
                    text: "dynamic tool request failed".to_string(),
                }],
                success: false,
            },
        },
        _ => return Ok(()),
    };
    thread.submit(response).await?;
    Ok(())
}
