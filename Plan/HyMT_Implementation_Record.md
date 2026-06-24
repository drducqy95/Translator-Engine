# Hy-MT Implementation Record & Plan

## Mục tiêu
Hy-MT (Hy-MT1.5-1.8B) làm fallback offline khi cloud provider hết quota/lỗi mạng,
và dần chuyển thành primary engine khi hệ thống đã tích lũy đủ knowledge graph.

---

## 1. Hiện trạng (đã hoàn thành)

### 1.1 Model & Build
- File GGUF: `models/hymt/Hy-MT1.5-1.8B-2bit.gguf` (600MB, 2-bit quant)
- llama.cpp build: `/root/llama.cpp/build-nosssl/bin/llama-server` (build 2026-06-24)
- Server flags: `-t 4 -c 4096 --no-ui` (không GPU, ARM CPU 4 threads)

### 1.2 Binary & Script
- `bin/hymt_server.sh`: tự detect `llama-server` path, fallback `/root/llama.cpp/build-nosssl/bin/llama-server`
- `bin/hymt_keepalive.sh`: watchdog loop, restart server khi crash
- PM2 daemon `hymt-llama` (đã test stop/start/resurrection)

### 1.3 Tích hợp Pipeline
- `stage3_ai_refiner.py`: split sub-chapter (~300 từ) + context trimming (chỉ giữ entity trong sub-chapter)
- `stage3_offline_hymt.py`: JSON parser → line-mode fallback → single-segment retry
- `ai_client.py`: priority `local_hymt` (priority 2, `role: offline_fallback`)
- `ai_providers.json`: `"enabled": false` (hiện tại tắt)

### 1.4 Các thành phần liên quan
- `stage2_context_pack.py`: QT pre-translation + filter locked_dict theo chapter
- `stage4_post_process.py`: CJK assertion cứng, filename `Chương XXXX <title>.md`
- `qc_checker.py`: CJK > 0 → hard error

---

## 2. Vấn đề hiện tại (cần hoàn thiện)

### 2.1 Performance
- **Inference quá chậm trên ARM**: 1.8B 2-bit quant, 4 threads, cần 30-90s cho 50 tokens
- **Context bị giới hạn**: `-c 4096` nhưng model gốc hỗ trợ 262144 → cần tăng từ từ
- **Prompt vẫn lớn**: dù đã trim context, mỗi sub-chapter vẫn gửi locked dict + TM + pronouns

### 2.2 Chất lượng dịch
- Hy-MT là translation model (không phải instruction-tuned) → JSON output hay bị lỗi format
- Fallback line-mode hoạt động nhưng mất thông tin entity/timeline
- Cần `--chat-template` phù hợp (hiện đang dùng template mặc định `hy_begin_of_sentence`)

### 2.3 Pipeline
- Stage 3 timeout cần điều chỉnh theo từng provider (local_hymt = 600s, cloud = 120s)
- Cần cache prompt-completion để tránh gọi lại segment đã dịch
- Cần batch inference: gửi nhiều segment trong 1 request

---

## 3. Roadmap hoàn thiện

### Phase A: Nền tảng inference
- [ ] Thử nghiệm với context `-c 8192`, `-c 16384`, đo latency/token
- [ ] Tối ưu prompt: loại bỏ hoàn toàn locked dict khỏi prompt (QT đã xử lý)→ AI chỉ rewrite
- [ ] Cache TM + QT output để không gọi lại translate()

### Phase B: Chất lượng
- [ ] Thử nghiệm `--chat-template` variants (chatml, llama3, command-r)
- [ ] Test với seed entity đã đủ lớn (>500 entities) để Hy-MT ít lỗi hơn
- [ ] So sánh chất lượng: Hy-MT vs cloud LLM trên 10 chương mẫu

### Phase C: Production
- [ ] Khi knowledge graph đủ lớn (>2000 entities, >5000 TM hits) → bật `"enabled": true`
- [ ] Tích hợp `--cont-batching` cho nhiều request đồng thời
- [ ] Healthcheck tự động: nếu Hy-MT không response trong 30s → fallback cloud

### Phase D: Tối ưu ARM
- [ ] Thử nghiệm `-ngl 0` (CPU-only) vs GPU acceleration nếu có
- [ ] Giảm `-t 2` nếu CPU heat/throttle
- [ ] Tăng `-c 16384` + giảm `max_chars` cho sub-chapter

---

## 4. Lệnh tham khảo

```bash
# Start manually
llama-server -m "models/hymt/Hy-MT1.5-1.8B-2bit.gguf" --host 127.0.0.1 --port 8088 -t 4 -c 4096 --no-ui

# Via PM2
pm2 start /root/llama.cpp/build-nosssl/bin/llama-server --name hymt-llama -- \
  -m "/sdcard/My Agent/Translator Engine/models/hymt/Hy-MT1.5-1.8B-2bit.gguf" \
  --host 127.0.0.1 --port 8088 -t 4 -c 4096 --no-ui

# Test single inference
curl -X POST http://127.0.0.1:8088/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Hy-MT1.5-1.8B-2bit","messages":[{"role":"user","content":"Translate: Hello world."}],"temperature":0.1,"max_tokens":64}'

# Restore ai_providers (bật Hy-MT)
# Sửa "enabled": false → true
```

---

## 5. File quan trọng

| File | Vai trò |
|------|---------|
| `Script/stage3_ai_refiner.py` | Split + trim context + gọi AI |
| `Script/stage3_offline_hymt.py` | JSON parser + line-mode fallback + single-segment retry |
| `Script/ai_client.py` | Provider priority + cooldown |
| `ai_providers.json` | Provider config (`enabled: false`) |
| `bin/hymt_server.sh` | Start llama-server |
| `bin/hymt_keepalive.sh` | Watchdog restart |
| `Script/stage2_context_pack.py` | QT pre-translate + filter locked dict |
| `Plan/HyMT_Offline_Fallback_TOS_Plan.md` | Plan gốc (design architecture) |
