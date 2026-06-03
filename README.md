# 實戰持股 · 綜合安全儀表板

**柏立推薦組：** PFE, GIS, FLO · **父親自選組：** NOK, NVO

100 分制評分：FCF (40) + 股息成長 (30) + 發放率 (20) + Beta (10)

## Install

```powershell
cd C:\Users\bauer\Projects\dividend-analyzer
pip install -r requirements.txt
```

## Web dashboard (Streamlit)

```powershell
streamlit run app.py
```

Browser opens at **http://localhost:8501**

## Terminal (optional)

```powershell
python analyze_dividend_screen.py
```

## Project layout

| File | Purpose |
|------|---------|
| `analyzer_core.py` | SEC + yfinance + 100-point scoring |
| `app.py` | Streamlit + Plotly dashboard |
| `analyze_dividend_screen.py` | Rich CLI output |
