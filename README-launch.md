# Launch Strix (local fork)

```bash
# 1. Install / reinstall the CLI from this checkout
pipx install --force "$PWD"
# (after editing python source, repeat the above to ship the new code)

# 2. Build the sandbox image so it carries the latest tools
docker build -t strix-sandbox:local -f containers/Dockerfile .

# 3. Point Strix at the local image (persist in your shell rc if desired)
export STRIX_IMAGE=strix-sandbox:local
export ANTHROPIC_API_KEY=...
# 4. Sanity-check everything before scanning
strix doctor
# all five checks must be green; otherwise run the printed fix.

# 5. Launch
strix -t https://your-target.example.com \
      --instruction "Use credentials demo@x / testtest"
# or: ./launch.sh
```

After source edits, the only steps that need re-running are the ones whose
inputs changed:

- Edited Python under `strix/` → `pipx install --force "$PWD"`
- Edited anything under `containers/` or any tool registered with
  `sandbox_execution=True` → rebuild the sandbox image (step 2). `strix doctor`
  will flag this drift before a scan blows up.
