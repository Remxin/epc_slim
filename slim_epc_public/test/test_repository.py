"""Layer 2: Repository - SQLite state and invariants.

Scope:
- UE lifecycle: attach/get/list/detach flows
- Bearer add/remove behavior
- Invariants: default bearer 9, cannot delete bearer 9
- Persisted updates: update_bearer, update_stats, save_ue
- Reset behavior: reset_all
"""
