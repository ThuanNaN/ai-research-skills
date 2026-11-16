---
# Enforced by hooks. Strings are double-quoted; paths are relative to the
# project root unless absolute. Editing this file asks for your confirmation.
enforce: true
stale_after_hours: 24

protected_paths:
  # No overwrite, edit, move or delete. Copying from them is fine.
  # - "scripts/rq1_*.py"
  # - "/data/myproject/outputs/step*/**"

eval_only_paths:
  # Must never appear in a training command.
  # - "data/heldout.json"

train_command_patterns:
  # Regular expressions that identify a training launch.
  # - "train\\.py|accelerate launch"

protected_processes:
  # Never kill these.
  # - "llama-server"
---

# Standing rules

- Do not start training without my approval.
- Copy a script before modifying it; never edit the original.
- Report every seed and every variant tried, including the bad ones.
