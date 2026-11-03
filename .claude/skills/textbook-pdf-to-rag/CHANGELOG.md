# 更新紀錄

版本號對應 SKILL.md frontmatter 的 `metadata.version`。

## 2（2026-11-04）
- 新增 `scripts/pipeline_status.py`：只讀檢查工作目錄每段的狀態（完成／部分／未做／過期／執行中／不需要）並建議下一步。
- 每個階段腳本新增 `--json`，把畫面上的統計同時寫成 JSON（共用 `scripts/stage_report.py`）；收尾報告的數字改從這些 JSON 取。
- `run_mineru.py`：輸出資料夾加鎖檔，避免同時跑兩個 MinerU；輸出先寫 `.part` 再改名，中斷不會留下半份檔案。
- SKILL.md 新增「缺少某個條件時，其他段照做」與「會跑很久的步驟」（工具呼叫逾時不等於 OCR 失敗）。
- 新增 `tests/`（腳本的 pytest 測試）。

## 1
- 第一版：切分、MinerU OCR、清理、字型提示、切塊、父子片段與 Chroma，含 Stewart 微積分與 Kurose 網路兩份設定檔範例。
