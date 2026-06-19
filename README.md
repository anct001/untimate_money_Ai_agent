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
  router.py              # LLMRouter: chọn tier + quota + fallback
  usage.py               # đếm request/ngày, tôn trọng giới hạn free-tier
  agent.py               # vòng lặp: plan -> draft -> tự phản biện -> hoàn thiện
  ledger.py              # sổ doanh thu THẬT, tiến độ tới mục tiêu
  workflows/             # các plugin kiếm tiền hợp pháp
    content.py           #   1) freelance / content (tạo bản nháp để bạn duyệt)
    saas_automation.py   #   2) SaaS: biến agent thành API tính phí (FastAPI)
    trading_signals.py   #   3) phân tích kỹ thuật — CHỈ tư vấn, không tự đặt lệnh
  __main__.py            # CLI
```

Tác vụ được gắn nhãn **`light`** (rẻ, hợp local) hoặc **`heavy`** (cần model mạnh).
Router thử các provider theo thứ tự trong config, bỏ qua cái nào bị tắt / không key /
offline / hết quota, và fallback khi lỗi.

## Lệnh CLI

```bash
python -m moneyagent providers                 # trạng thái & quota từng nguồn
python -m moneyagent chat "viết email xin lỗi khách" 
python -m moneyagent content --topic "Lợi ích của đạp xe" --words 700 --language Vietnamese
python -m moneyagent signals --prices 10,11,12,11,13,14,...   # hoặc --ticker BTC-USD (cần yfinance)
python -m moneyagent ledger                    # tiến độ tháng này
python -m moneyagent ledger --add --source content --desc "blog cho khách A" --amount 150 --status paid
python -m moneyagent serve                     # chạy SaaS API (cần fastapi uvicorn)
```

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
python -m pytest -q     # chạy offline, không cần mạng (dùng fake provider)
```

## Giới hạn & nguyên tắc

- Không spam, không tài khoản ảo, không lách ToS của nhà cung cấp.
- Không tự động giao dịch tiền thật; không hứa lợi nhuận.
- Mọi đầu ra hướng tới khách hàng/công chúng đều cần **người duyệt** trước.
- Đây là công cụ tăng tốc công việc thật, không phải máy in tiền.

## Roadmap gợi ý

- Thêm provider free khác (Cerebras, Together) — chỉ cần thêm block vào config.
- Tool-use thật cho agent (web search, đọc file) qua interface tool.
- Hàng đợi job + scheduler để chạy workflow định kỳ.
- Tích hợp Stripe cho hướng SaaS.
