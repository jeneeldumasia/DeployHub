import os
from pathlib import Path

adr_dir = Path('c:/Project/ShipZen/docs/adr')

for file in adr_dir.glob('*.md'):
    content = file.read_text(encoding='utf-8')
    content = content.replace('**Status:** PROPOSED (Awaiting ACCEPTED)', '**Status:** ACCEPTED')
    
    if '0008-secret-management.md' in file.name:
        content = content.replace(
            '**Decision:** Centralized secret management via AWS Secrets Manager. External Secrets Operator (ESO) will sync these into per-tenant Kubernetes Secrets.',
            '**Decision:** Centralized secret management via AWS Secrets Manager. External Secrets Operator (ESO) will sync these into per-tenant Kubernetes Secrets. Secrets injected via ESO `envFrom` or `volumeMount` are permitted — only hardcoded plaintext values are forbidden.'
        )
    
    file.write_text(content, encoding='utf-8')

print("Updated all ADRs to ACCEPTED.")
