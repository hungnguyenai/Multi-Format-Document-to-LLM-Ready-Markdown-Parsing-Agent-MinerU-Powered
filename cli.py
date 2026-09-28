"""AGENTIC STAR Marketplace entrypoint — one-shot Pod process.

Duoc Dockerfile goi qua CMD ["python", "cli.py"]. Compile agent, cap secrets,
roi ban giao cho shared.bootstrap.marketplace_app lo vong doi Marketplace.

Lop duoi day PHAI khop `class:` trong config/agent.yaml. Ban mac dinh cua bo
deploy hard-code `Graph`, nen repo nao co lop ten khac se ImportError ngay khi
container start — build, push va dang ky deu van xanh.

Repo nay CO config/config.yaml va gia tri trong do LAM DOI KET QUA, nen phai
nap tuong minh: runner khong tu doc file do.
"""

from pathlib import Path

from framework.utils.config_loader import load_agent_config
from src.graph.graph import MultiFormatDocumentParsingAgent
from shared.bootstrap.marketplace_app import run_agent_marketplace

if __name__ == "__main__":
    run_agent_marketplace(
        MultiFormatDocumentParsingAgent,
        agent_name="cmn_c1_127",
        namespace="cmn-c1-127",
        config=load_agent_config(Path(__file__).resolve().parent),
    )
