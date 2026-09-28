"""Standalone HTTP entry point for CMN-C1-127.

Entry points are adapters only — no business logic here. Secrets are provisioned once at
startup (provision_secrets) and bound per-request via bound_secrets (S-3); the agent and its
nodes never read process environment variables for secrets. For platform-level routing,
AgentGateway calls agent.invoke() directly. The request body is {"input": "<envelope>",
"session_id": "..."}, where the envelope is the JSON document payload
({"documents": [...], "output_format": "..."}) forwarded verbatim as the agent user_input.
"""

from uuid import uuid4

from fastapi import FastAPI, Request
from pydantic import BaseModel

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets import factory as secrets_factory

from src.graph.graph import Graph

app = FastAPI(title="CMN-C1-127 — Multi-Format Document Parsing Agent")

agent = Graph()
agent.compile()
agent.provision_secrets(secrets_factory(namespace="cmn-c1-127", agent_name="cmn-c1-127"))


class InvokeRequest(BaseModel):
    input: str
    session_id: str = ""


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request):
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            # Documents are caller-supplied external content (S-1: VERIFIED_EXTERNAL).
            caller_trust_level=getattr(request.state, "trust_level", TrustLevel.VERIFIED_EXTERNAL),
            caller_id=getattr(request.state, "caller_id", ""),
        )
        return agent.invoke(req.input, ctx=ctx)


@app.get("/health")
def health():
    return {"status": "ok", "agent": "cmn-c1-127"}
