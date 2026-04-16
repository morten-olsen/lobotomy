.PHONY: setup init index search hooks

setup:
	cd tools && uv sync

init: setup hooks
	@echo "Setup complete. Run 'claude' and type /setup to configure your wiki."

index:
	uv run --directory tools lobotomy index

search:
	uv run --directory tools lobotomy search $(ARGS)

hooks:
	cp hooks/post-merge .git/hooks/post-merge 2>/dev/null || true
	chmod +x .git/hooks/post-merge 2>/dev/null || true
