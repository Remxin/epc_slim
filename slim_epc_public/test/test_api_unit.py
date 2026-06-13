"""Layer 3: Endpoint unit logic - direct handler calls with mocks.

Scope:
- Success and failure branches per handler
- ValueError -> HTTPException(400) mapping
- Behavior depending on mocked repo/traffic-manager state
- Aggregation decisions in GET /ues/stats
"""
