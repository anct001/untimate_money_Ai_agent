# moneyagent

Một **AI agent framework** kết hợp **local model nhỏ (Ollama)** với các **API free-tier**
(Groq, Gemini, OpenRouter, Cerebras…) sau một **router** duy nhất lo việc chọn model,
theo dõi quota và **tự động fallback**. Trên nền đó là các **workflow** giúp bạn làm
công việc thật, hợp pháp, nhanh hơn.

> ### Nói thẳng về mục tiêu "$10.000/tháng"
> Không có phần mềm nào (kể cả cái này) **đảm bảo** kiếm $10k/tháng tự động. Doanh thu
> đến từ giá trị thật bạn giao cho khách hàng, không phải từ việc bật một script.
> Framework này **tăng tốc** công việc hợp pháp và **theo dõi tiến độ bằng số liệu thật**
> (xem `ledger`). Nó **không** làm spam, tạo tài khoản ảo, lách ToS, hay nội dung lừa đảo —
> những thứ đó vừa phạm luật vừa khiến tài khoản bị khóa và thực tế kiếm được rất ít.

## Vì sao "free": chi phí gần $0

Router ưu tiên **Ollama local** (miễn phí, riêng tư, không quota) cho việc nhẹ, rồi dùng
các **free-tier API** cho việc nặng, và **tự chuyển provider** khi một nguồn lỗi hoặc hết
quota trong ngày. Bạn cấu hình bao nhiêu provider tùy thích — có cái nào dùng cái đó.

## Cài đặt nhanh

```bash
pip install -r requirements.txt
cp .env.example .env          # điền API key của (các) nguồn bạn có — không cần đủ hết
cp config/config.example.yaml config/config.yaml   # (tùy chọn) tinh chỉnh

# Local model (tùy chọn, miễn phí):
#   ollama serve && ollama pull llama3.2:3b

python -m moneyagent providers   # kiểm tra nguồn nào đang sẵn sàng
```

## Kiến trúc

```
moneyagent/
  config.py              # defaults + config.yaml + .env
  providers/             # mỗi backend nói cùng một interface
    base.py              # Provider ABC, Message, CompletionResult
    openai_compat.py     # Groq / OpenRouter / Cerebras / Together / vLLM…
    gemini_provider.py   # Google Gemini REST
    ollama_provider.py   # local
    factory.py
  router.py              # LLMRouter: tier + quota + fallback + retry/backoff + budget
  usage.py               # đếm request/ngày + chi phí USD, tôn trọng giới hạn free-tier
  pricing.py             # bảng giá USD/1M token (model free = 0) để ước tính chi phí
  cache.py               # cache prompt trên đĩa -> tiết kiệm quota
  agent.py               # Agent (plan->draft->review) + ToolAgent (ReAct dùng tool)
  tools/                 # bộ tool an toàn: calculator, read_file, web_search, http_get
  memory.py              # bộ nhớ bền vững (JSONL) cho các lần chạy tự động
  jobs.py                # Autopilot: chạy workflow theo lịch, có guardrail
  ledger.py              # sổ doanh thu THẬT, tiến độ tới mục tiêu
  workflows/             # các plugin kiếm tiền hợp pháp
    content.py           #   1) freelance / content (tạo bản nháp để bạn duyệt)
    saas_automation.py   #   2) SaaS: biến agent thành API tính phí (FastAPI)
    trading_signals.py   #   3) phân tích kỹ thuật — CHỈ tư vấn, không tự đặt lệnh
  __main__.py            # CLI
```

Tác vụ được gắn nhãn **`light`** (rẻ, hợp local) hoặc **`heavy`** (cần model mạnh).
Router thử các provider theo thứ tự trong config, bỏ qua cái nào bị tắt / không key /
offline / hết quota / đang cooldown / rate-limit, và fallback khi lỗi.

### Khả năng chịu lỗi & chi phí (theo pattern LiteLLM)

- **Retry + exponential backoff** cho lỗi tạm thời (5xx / mạng) trước khi fallback.
- **429 (rate-limit)** → đánh dấu provider "hết quota trong ngày"; **lỗi auth** → tắt provider
  cả phiên; lỗi khác → **cooldown** ngắn rồi thử lại.
- **Ước tính chi phí USD** mỗi call (model free = $0) + **giới hạn ngân sách/ngày** chặn cứng
  chi tiêu nếu bạn lỡ dùng model trả phí.
- **Cache prompt**: yêu cầu giống hệt được trả từ đĩa, không tốn quota.

Tùy chỉnh trong `config.yaml` mục `router:` (`max_retries`, `cooldown_seconds`,
`daily_budget_usd`, `cache`).

## Lệnh CLI

```bash
python -m moneyagent providers                 # trạng thái, quota & chi phí từng nguồn
python -m moneyagent chat "viết email xin lỗi khách"
python -m moneyagent agent "tra cứu giá Bitcoin hôm nay và tính 3% của nó"  # ReAct + tool
python -m moneyagent tools                      # liệt kê tool agent dùng được
python -m moneyagent content --topic "Lợi ích của đạp xe" --words 700 --language Vietnamese
python -m moneyagent signals --prices 10,11,12,11,13,14,...   # hoặc --ticker BTC-USD (cần yfinance)
python -m moneyagent ledger                    # tiến độ tháng này
python -m moneyagent ledger --add --source content --desc "blog cho khách A" --amount 150 --status paid
python -m moneyagent autopilot --jobs config/jobs.yaml --once   # chạy job; bỏ --once để chạy liên tục
python -m moneyagent serve                     # chạy SaaS API (cần fastapi uvicorn)
```

### Autopilot — chạy tự động (có guardrail)

`autopilot` đọc `config/jobs.yaml` (mẫu: `config/jobs.example.yaml`) và chạy các workflow
theo `every_seconds`/`max_runs`, **tôn trọng quota + ngân sách**, ghi kết quả ra `outputs/`
và log vào `data/memory.jsonl`. **Không tự động đăng/gửi cho khách** — bạn vẫn duyệt rồi giao.

## Ba hướng kiếm tiền (hợp pháp)

1. **Freelance / Content** (`content.py`) — agent tạo **bản nháp** (bài viết, dịch, rewrite)
   để bạn fact-check & biên tập rồi giao cho khách. Có cảnh báo `[verify]` ở chỗ cần kiểm chứng.
   *Bạn vẫn là người chịu trách nhiệm và giao hàng.*
2. **SaaS automation** (`saas_automation.py`) — đóng gói một việc lặp đi lặp lại (tóm tắt,
   nháp trả lời…) thành **API tính phí subscription**. Module cho sẵn lõi `request -> agent ->
   response`; bạn thêm auth, billing (Stripe), rate-limit, UI.
3. **Trading signals** (`trading_signals.py`) — tính chỉ báo kỹ thuật minh bạch (SMA, RSI,
   trend) và viết bản tin **giáo dục, có cảnh báo rủi ro**. **Không bao giờ tự đặt lệnh tiền thật.**

## Theo dõi mục tiêu một cách trung thực

`ledger` chỉ ghi nhận **doanh thu thật** bạn nhập vào (từ công việc đã hoàn thành / hóa đơn),
rồi tính % tiến độ tới `monthly_target_usd`. Agent **không tự bịa doanh thu**. Đây là cách
duy nhất để "$10k/tháng" có ý nghĩa: dựa trên số liệu thật.

## Test

```bash
python -m pytest -q     # 23 test, chạy offline, không cần mạng (dùng fake/scripted provider)
```

## Giới hạn & nguyên tắc

- Không spam, không tài khoản ảo, không lách ToS của nhà cung cấp.
- Không tự động giao dịch tiền thật; không hứa lợi nhuận.
- Mọi đầu ra hướng tới khách hàng/công chúng đều cần **người duyệt** trước.
- Đây là công cụ tăng tốc công việc thật, không phải máy in tiền.

## Đã có trong bản này (nâng cấp theo các dự án tương tự)

Tham khảo pattern từ **LiteLLM** (router/fallback/retry/cost), **AutoGPT / Hermes / agno /
OpenManus** (tool access, chạy liên tục, bộ nhớ):

- ✅ Retry + exponential backoff, cooldown, xử lý 429/auth theo từng provider.
- ✅ Ước tính chi phí USD + giới hạn ngân sách/ngày + cache prompt.
- ✅ ToolAgent kiểu **ReAct** (provider-agnostic, chạy cả với local model nhỏ).
- ✅ Bộ tool an toàn (calculator/read_file sandbox/web_search/http_get).
- ✅ **Autopilot** scheduler + bộ nhớ bền vững để chạy workflow tự động có guardrail.

## Roadmap gợi ý tiếp theo

- Thêm provider free khác (Cerebras, Together) — chỉ cần thêm block vào config.
- Multi-agent "crew" (nhiều persona) cho phân tích trading (kiểu ai-hedge-fund).
- Tích hợp Stripe + auth cho hướng SaaS để bán subscription thật.
- Vector memory (embeddings) thay cho memory JSONL hiện tại.
