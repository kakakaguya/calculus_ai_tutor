# 1 MinerU OCR → Markdown

## 安裝（先徵得同意：模型約 2 GB，需要 NVIDIA GPU）
MinerU 的相依套件多，放在獨立虛擬環境，避免和專案環境衝突：
```bash
python3 -m venv .venv-mineru
.venv-mineru/bin/pip install "mineru>=4.0,<5"      # 4.0.10 實測可用
.venv-mineru/bin/mineru-kit models download --tier standard
```
`mineru-kit parse --help` 可確認目前版本的參數。版本 5 以後參數可能改名，以 help 為準。

## 執行
```bash
python3 $S/run_mineru.py --input pdf_split --output markdown \
    --mineru-kit .venv-mineru/bin/mineru-kit --limit 2     # 先試兩份
```
試跑後打開輸出，對照 PDF 看三件事：公式是不是 LaTeX、`\delta`、`>`、`\geq` 有沒有讀錯、
段落順序對不對。沒問題再拿掉 `--limit` 全量跑。

## 全量跑：放背景，逾時不等於失敗
一份 5 頁約 3 分鐘，195 份約 10 小時，遠超過一次工具呼叫能等的時間（常見上限 10 分鐘）。
所以全量一定放背景，輸出寫到記錄檔：
```bash
nohup python3 $S/run_mineru.py --input pdf_split --output markdown \
    --mineru-kit .venv-mineru/bin/mineru-kit --json reports/ocr.json > ocr.log 2>&1 &
```
（有背景執行功能的工具，例如 Claude Code 的 `run_in_background`，也可以直接用。）

**工具呼叫逾時、或對話中斷，不代表 OCR 停了。** MinerU 很可能還在背景跑。這時：
1. 先跑 `pipeline_status.py`：它會顯示「1 OCR 執行中（PID …）」和已轉幾份。
2. 還在跑就等，過一陣再查；看 `ocr.log` 的最後幾行可知目前轉到哪份。
3. **不要再啟動一次。** 兩個 MinerU 會搶同一張 GPU（常見結果是 CUDA out of memory），
   還會同時寫同一個資料夾。`run_mineru.py` 會用輸出資料夾裡的 `.run_mineru.lock`
   擋下第二次啟動；被擋時照訊息做，不要刪鎖檔硬跑。
4. 確認已經停了（狀態不再是執行中）才用同一個指令重跑：已完成的會略過，從中斷處接續。
   被強制中止的程序留下的鎖檔，下次執行會自動接手，不必手動刪。

## 重要設定與原因
- `--ocr-mode ocr`（預設）：PDF 的文字層常把數學符號對應錯（δ 消失、> 變 ≥），
  強制 OCR 比較準。只有確定文字層正確的純文字講義才考慮 `auto`。
- `--tier standard`：版面＋OCR 模型加上 1.2B 的公式模型。`flash`/`basic` 較快但公式差。
- 絕不加 `--remote`：那會把頁面送到 mineru.net。
- 每份 Markdown 開頭會加 `<!-- extractor: mineru -->`，後續腳本靠它認出 MinerU 輸出。

## 中斷、失敗與重跑
- 已存在的輸出一律略過，所以中斷後直接再跑同一個指令就會接續。輸出先寫成 `.part`
  再改名，中斷時不會留下半份 Markdown 被誤當成已完成。
- 失敗的檔名會列在最後，`--json` 報告的 `failed` 也有每份的錯誤訊息；確認原因
  （單份逾時、GPU 記憶體）後用 `--redo 檔名.pdf` 單獨重跑。
- **不要為了「重新整理」而刪掉整個 markdown 資料夾重跑**：使用者可能手動修過某些檔案。
  先問，並把手動修過的列進 `book_profile.json` 的 `protected_files`。

## 沒有 GPU 時
MinerU 在 CPU 上極慢（一份可能數十分鐘）。可以先只跑少數幾份確認流程，
或告知使用者需要 GPU 機器。其他擷取工具（pypdf 文字層、Docling）公式品質明顯較差，
若使用要在報告中明說，而且公式相關的驗收要更嚴。
