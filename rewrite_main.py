from pathlib import Path

engine_dir = Path("/sdcard/my agent/Translator Engine")
bot_file = engine_dir / "telegram_bot_v2.py"
lines = bot_file.read_text(encoding="utf-8").splitlines()

# find daemon start
daemon_start = 0
for i, line in enumerate(lines):
    if line.startswith("def daemon_raw_processing():"):
        daemon_start = i
        break

# find end of daemons
main_loop_idx = 0
for i in range(daemon_start, len(lines)):
    if lines[i].startswith("print(") or "infinity_polling" in lines[i]:
        main_loop_idx = i
        break

main_lines = lines[:daemon_start] + [
    "from Bot.daemons import daemon_raw_processing, daemon_project_init, daemon_pipeline_executor"
] + lines[main_loop_idx:]

bot_file.write_text("\n".join(main_lines), encoding="utf-8")
print("Rewritten telegram_bot_v2.py")
