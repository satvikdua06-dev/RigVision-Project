# ──────────────────────────────────────────────────────────
# RigVision-3D — Makefile
# ──────────────────────────────────────────────────────────
# Developer shortcuts. Run with: make <target>
#
# Quick start:
#   make up        → start Docker infrastructure
#   make demo      → run full demo (backend + CV demo + frontend)
# ──────────────────────────────────────────────────────────

.PHONY: up down backend frontend cv-demo cv-live demo install clean logs

# ── Infrastructure ──

up:
	docker compose up -d
	@echo "✅ Infrastructure started. Services:"
	@echo "   Redis:     localhost:6379"
	@echo "   Postgres:  localhost:5432"
	@echo "   Neo4j:     http://localhost:7474"
	@echo "   EMQX:      http://localhost:18083"

down:
	docker compose down

logs:
	docker compose logs -f

# ── Individual Services ──

backend:
	cd backend && python main.py

frontend:
	cd frontend && npm run dev

cv-demo:
	cd cv && python pipeline.py --mode demo

cv-live:
	cd cv && python pipeline.py --mode live --cameras 0 1 2

# ── Combo Commands ──

# Full demo: requires 3 terminal windows
demo:
	@echo "🚀 RigVision-3D Demo Mode"
	@echo "Run these in 3 separate terminals:"
	@echo ""
	@echo "  Terminal 1:  make backend"
	@echo "  Terminal 2:  make cv-demo"
	@echo "  Terminal 3:  make frontend"
	@echo ""
	@echo "Then open: http://localhost:3000"

# ── Setup ──

install:
	cd backend && pip install -r requirements.txt
	cd cv && pip install -r requirements.txt
	cd frontend && npm install
	@echo "✅ All dependencies installed"

clean:
	docker compose down -v
	rm -rf frontend/node_modules frontend/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned up"
