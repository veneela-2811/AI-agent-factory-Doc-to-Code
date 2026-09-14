import asyncio
import json
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from config.settings import settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from src.auth.jwt import decode_access_token
import src.storage.database as db_module
from src.storage.models import Project, Run
from src.observability.events import event_hub
from src.workflows.runner import workflow_runner
from src.workflows.requirements.graph import build_requirements_graph

logger = logging.getLogger("ws_hitl")
router = APIRouter(tags=["Human-in-the-Loop"])

# Active connections: (project_id, run_id) -> WebSocket
active_hitl_sockets: Dict[str, WebSocket] = {}


@router.websocket("/projects/{project_id}/runs/{run_id}/hitl")
async def websocket_hitl_endpoint(
    websocket: WebSocket,
    project_id: str,
    run_id: str,
    token: Optional[str] = Query(default=None)
):
    # 1. JWT Handshake Validation
    auth_header = websocket.headers.get("authorization", "")
    jwt_token = token
    if not jwt_token and auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:].strip()

    if not jwt_token:
        subprotocols = websocket.scope.get("subprotocols", [])
        if subprotocols:
            jwt_token = subprotocols[0]

    if not jwt_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing JWT token")
        return

    try:
        claims = decode_access_token(jwt_token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired JWT")
        return

    # Verify run exists and belongs to project
    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(Run).where(Run.id == run_id, Run.project_id == project_id)
        )
        run_record = res.scalar_one_or_none()
        if not run_record:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Run not found in project")
            return

    # Single active subscriber per run_id
    socket_key = f"{project_id}_{run_id}"
    if socket_key in active_hitl_sockets:
        old_ws = active_hitl_sockets[socket_key]
        try:
            await old_ws.close(code=4009, reason="New subscriber connected")
        except Exception:
            pass

    subprotocols = websocket.scope.get("subprotocols", [])
    selected_subprotocol = subprotocols[0] if subprotocols else None
    await websocket.accept(subprotocol=selected_subprotocol)
    active_hitl_sockets[socket_key] = websocket
    logger.info(f"[{run_id}] WebSocket HITL client connected.")

    # Check for pending interrupts upon connection / reconnection (Spec lines 260 & 412)
    try:
        db_path = str(settings.CHECKPOINT_DB_PATH.resolve())
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            config = {"configurable": {"thread_id": f"{project_id}_{run_id}", "project_id": project_id, "run_id": run_id}}
            compiled_graph = build_requirements_graph().compile(checkpointer=checkpointer)
            graph_state = await compiled_graph.aget_state(config)
            if graph_state.tasks:
                for task in graph_state.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            intr_data = intr.value
                            if isinstance(intr_data, dict):
                                await websocket.send_text(json.dumps(intr_data))
    except Exception as e:
        logger.warning(f"[{run_id}] Error checking pending interrupts on connect: {e}")

    # Background task to stream push interrupts from event_hub to WebSocket
    async def _event_stream_to_ws():
        try:
            async for event in event_hub.subscribe(project_id, run_id):
                evt_type = event.get("event")
                data = event.get("data", {})
                if evt_type in ["clarification_requested", "approval_requested", "run_completed", "error"]:
                    if isinstance(data, dict) and "type" in data:
                        await websocket.send_text(json.dumps(data))
                    else:
                        msg = {
                            "type": evt_type,
                            "request_id": data.get("request_id") if isinstance(data, dict) else None,
                            "payload": data
                        }
                        await websocket.send_text(json.dumps(msg))
        except Exception as e:
            logger.debug(f"[{run_id}] Event stream task closed: {e}")

    stream_task = asyncio.create_task(_event_stream_to_ws())

    # Heartbeat loop
    async def _heartbeat():
        try:
            while True:
                await asyncio.sleep(20)
                await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat())

    # Receive loop for human responses
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON format"}))
                continue

            msg_type = msg.get("type")
            logger.info(f"[{run_id}] WS received message type: '{msg_type}'")

            if msg_type == "pong":
                continue
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "clarification_response":
                answers = msg.get("answers", msg.get("payload", {}).get("answers", []))
                await workflow_runner.resume_run(project_id, run_id, {"answers": answers})
                await websocket.send_text(json.dumps({"type": "ack", "status": "resumed_clarification"}))
            elif msg_type == "approval_response":
                decision = msg.get("decision", msg.get("payload", {}).get("decision", "approve"))
                feedback = msg.get("feedback", msg.get("payload", {}).get("feedback"))
                await workflow_runner.resume_run(project_id, run_id, {"decision": decision, "feedback": feedback})
                await websocket.send_text(json.dumps({"type": "ack", "status": "resumed_approval", "decision": decision}))
            else:
                await websocket.send_text(json.dumps({"type": "unexpected_message", "received": msg_type}))

    except WebSocketDisconnect:
        logger.info(f"[{run_id}] WS client disconnected.")
    finally:
        stream_task.cancel()
        heartbeat_task.cancel()
        if active_hitl_sockets.get(socket_key) == websocket:
            del active_hitl_sockets[socket_key]


@router.get("/hitl-console", summary="Interactive Browser WebSocket HITL Test Console", include_in_schema=False)
async def hitl_browser_console():
    from fastapi.responses import HTMLResponse
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>AI Agent Factory - HITL WebSocket Console</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; max-width: 900px; margin: 0 auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
        h2 { margin-top: 0; color: #38bdf8; }
        label { display: block; margin-top: 12px; font-weight: 600; font-size: 13px; color: #94a3b8; }
        input, textarea { width: 100%; box-sizing: border-box; padding: 10px; border-radius: 6px; border: 1px solid #334155; background: #0f172a; color: #f8fafc; font-family: monospace; font-size: 13px; margin-top: 4px; }
        .row { display: flex; gap: 12px; }
        .col { flex: 1; }
        button { background: #0284c7; color: white; border: none; border-radius: 6px; padding: 10px 18px; font-weight: 600; cursor: pointer; margin-top: 12px; transition: background 0.2s; }
        button:hover { background: #0369a1; }
        button.success { background: #16a34a; }
        button.success:hover { background: #15803d; }
        button.danger { background: #dc2626; }
        button.danger:hover { background: #b91c1c; }
        #logs { height: 320px; overflow-y: auto; background: #090d16; border-radius: 6px; border: 1px solid #1e293b; padding: 12px; font-family: monospace; font-size: 12px; white-space: pre-wrap; margin-top: 16px; color: #38bdf8; }
        .status-badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; background: #334155; color: #94a3b8; }
        .connected { background: #166534; color: #4ade80; }
        .disconnected { background: #991b1b; color: #f87171; }
        .action-box { background: #0f172a; border: 1px solid #38bdf8; border-radius: 8px; padding: 16px; margin-top: 16px; display: none; }
    </style>
</head>
<body>
    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h2>AI Agent Factory - HITL Interactive Console</h2>
            <span id="statusBadge" class="status-badge disconnected">Disconnected</span>
        </div>
        
        <div class="row">
            <div class="col">
                <label>Project ID:</label>
                <input id="projectId" placeholder="Project UUID" />
            </div>
            <div class="col">
                <label>Run ID:</label>
                <input id="runId" placeholder="Run UUID" />
            </div>
        </div>
        <label>JWT Access Token:</label>
        <input id="jwtToken" placeholder="eyJhbGciOiJIUzI1NiIs..." />
        
        <div style="display:flex; gap:10px;">
            <button id="connectBtn" onclick="connectWS()">Connect WebSocket</button>
            <button id="disconnectBtn" onclick="disconnectWS()" style="display:none; background:#475569;">Disconnect</button>
        </div>

        <div id="actionBox" class="action-box">
            <h3 id="actionTitle" style="margin-top:0; color:#38bdf8;">Pending Action</h3>
            <div id="actionDetails" style="margin-bottom:12px; font-size:13px;"></div>
            <div id="clarifySection" style="display:none;">
                <label>Answer (JSON or text):</label>
                <textarea id="clarifyAnswer" rows="2" placeholder='Use SQLite and ChromaDB for persistence'></textarea>
                <button class="success" onclick="sendClarification()">Submit Clarification Answers</button>
            </div>
            <div id="approvalSection" style="display:none; display:flex; gap:10px;">
                <button class="success" onclick="sendApproval('approve')">Approve Specification</button>
                <button class="danger" onclick="sendApproval('reject')">Reject with Feedback</button>
            </div>
        </div>

        <label style="margin-top:16px;">Live WebSocket Event Log:</label>
        <div id="logs">[Console ready. Enter details above and click Connect]</div>
    </div>

    <script>
        let ws = null;
        let lastRequestId = null;
        let lastQuestions = [];

        function log(msg) {
            const el = document.getElementById('logs');
            el.textContent += '\\n[' + new Date().toLocaleTimeString() + '] ' + msg;
            el.scrollTop = el.scrollHeight;
        }

        function connectWS() {
            const pId = document.getElementById('projectId').value.trim();
            const rId = document.getElementById('runId').value.trim();
            const token = document.getElementById('jwtToken').value.trim();

            if (!pId || !rId || !token) {
                alert('Please provide Project ID, Run ID, and JWT Token');
                return;
            }

            const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/projects/' + pId + '/runs/' + rId + '/hitl?token=' + encodeURIComponent(token);
            log('Connecting to ' + wsUrl + '...');

            try {
                ws = new WebSocket(wsUrl);

                ws.onopen = function() {
                    document.getElementById('statusBadge').textContent = 'Connected';
                    document.getElementById('statusBadge').className = 'status-badge connected';
                    document.getElementById('connectBtn').style.display = 'none';
                    document.getElementById('disconnectBtn').style.display = 'inline-block';
                    log('WebSocket Connected successfully! Listening for HITL events...');
                };

                ws.onmessage = function(event) {
                    log('Received Message: ' + event.data);
                    try {
                        const data = JSON.parse(event.data);
                        handleIncoming(data);
                    } catch(e) {}
                };

                ws.onclose = function(ev) {
                    document.getElementById('statusBadge').textContent = 'Disconnected';
                    document.getElementById('statusBadge').className = 'status-badge disconnected';
                    document.getElementById('connectBtn').style.display = 'inline-block';
                    document.getElementById('disconnectBtn').style.display = 'none';
                    document.getElementById('actionBox').style.display = 'none';
                    log('WebSocket closed. Code: ' + ev.code + ', Reason: ' + (ev.reason || 'None'));
                };

                ws.onerror = function(err) {
                    log('WebSocket Error encountered.');
                };
            } catch(e) {
                log('Connection exception: ' + e);
            }
        }

        function disconnectWS() {
            if (ws) ws.close();
        }

        function handleIncoming(msg) {
            const actionBox = document.getElementById('actionBox');
            const actionTitle = document.getElementById('actionTitle');
            const actionDetails = document.getElementById('actionDetails');
            const clarifySec = document.getElementById('clarifySection');
            const approvalSec = document.getElementById('approvalSection');

            if (msg.type === 'clarification_request' || msg.type === 'clarification_requested') {
                lastRequestId = msg.request_id;
                lastQuestions = msg.questions || (msg.payload && msg.payload.questions) || [];
                actionBox.style.display = 'block';
                clarifySec.style.display = 'block';
                approvalSec.style.display = 'none';
                actionTitle.textContent = 'Clarification Requested (HITL)';
                actionDetails.innerHTML = '<strong>Agent identified ambiguous requirements:</strong><br>' +
                    lastQuestions.map(q => '&bull; [' + q.id + '] ' + q.question + ' <em>(' + (q.context || '') + ')</em>').join('<br>');
            } else if (msg.type === 'approval_request' || msg.type === 'approval_requested') {
                lastRequestId = msg.request_id;
                actionBox.style.display = 'block';
                clarifySec.style.display = 'none';
                approvalSec.style.display = 'flex';
                actionTitle.textContent = 'Specification Approval Required (HITL)';
                const art = msg.artifact || (msg.payload && msg.payload.artifact) || {};
                actionDetails.innerHTML = '<strong>Generated Specification Artifacts:</strong><br>' +
                    '&bull; Markdown Spec: <code>' + (art.requirements_md_url || 'requirements.md') + '</code><br>' +
                    '&bull; JSON Schema: <code>' + (art.requirements_json_url || 'requirements.json') + '</code>';
            } else if (msg.type === 'run_completed') {
                actionBox.style.display = 'none';
                log('Workflow 1 completed successfully!');
            }
        }

        function sendClarification() {
            const ansText = document.getElementById('clarifyAnswer').value || 'Standard local deployment';
            const answers = lastQuestions.map(q => ({ id: q.id, answer: ansText }));
            const payload = {
                type: 'clarification_response',
                request_id: lastRequestId,
                answers: answers
            };
            ws.send(JSON.stringify(payload));
            log('Sent clarification_response: ' + JSON.stringify(payload));
            document.getElementById('actionBox').style.display = 'none';
        }

        function sendApproval(decision) {
            const payload = {
                type: 'approval_response',
                request_id: lastRequestId,
                decision: decision,
                feedback: decision === 'reject' ? 'Please add HIPAA compliance constraints.' : null
            };
            ws.send(JSON.stringify(payload));
            log('Sent approval_response: ' + JSON.stringify(payload));
            document.getElementById('actionBox').style.display = 'none';
        }

        // Auto-fill query params if present
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('project_id')) document.getElementById('projectId').value = urlParams.get('project_id');
        if (urlParams.get('run_id')) document.getElementById('runId').value = urlParams.get('run_id');
        if (urlParams.get('token')) document.getElementById('jwtToken').value = urlParams.get('token');
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

