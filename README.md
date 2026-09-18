# 📊 Trading Monitor V10

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Twelve Data](https://img.shields.io/badge/Twelve%20Data-API-00ff88?style=for-the-badge&logo=chart-line&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)

![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)
![Version](https://img.shields.io/badge/Version-10.0.0-blue?style=for-the-badge)

**Plateforme de monitoring boursier en temps réel propulsée par Twelve Data**

*Indicateurs techniques • Signaux IA • Graphiques candlestick • Multi-actifs*

</div>

---

## 🎯 À propos

**Trading Monitor V10** est une application web de surveillance des marchés financiers en temps réel via l'API **Twelve Data**.

- 🥇 **Commodités** : Or, Argent, Pétrole
- ₿ **Crypto** : Bitcoin, Ethereum, Solana
- 💱 **Forex** : EUR/USD, GBP/USD, USD/JPY
- 🇺🇸 **US Stocks** : Apple, Microsoft, NVIDIA...
- 🇫🇷 **Paris** : LVMH, Sanofi, L'Oréal...
- 📈 **Indices** : S&P 500, Dow Jones, Nasdaq...
- 📊 **FUNDS** : ETF majeurs

---

## ✨ Fonctionnalités

- ✅ **Prix temps réel** sur 31 actifs
- ✅ **Graphiques candlestick** interactifs
- ✅ **10+ indicateurs techniques** (RSI, MACD, Bollinger...)
- ✅ **Signaux ACHAT/VENTE/NEUTRE** avec score de confiance
- ✅ **Stop-loss et take-profit** calculés
- ✅ **Données fondamentales** (P/E, dividende, beta...)
- ✅ **Cache intelligent** pour économiser les crédits API
- ✅ **Export CSV** et **comparateur** d'actifs

---

## 🚀 Installation

### Prérequis

- **Python 3.10+**
- **Clé API Twelve Data** gratuite : [twelvedata.com/register](https://twelvedata.com/register)

### Étapes

```bash
# 1. Cloner le repo
git clone https://github.com/ton-user/trading-monitor.git
cd trading-monitor

# 2. Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Créer le fichier .env
cp .env.example .env
# Édite .env et colle ta clé API Twelve Data

# 5. Lancer
python serv.py
```

Ouvre ensuite **http://localhost:5001**

---

## ⚙️ Configuration

Fichier `.env` à la racine :

```
TWELVE_DATA_API_KEY=ta_cle_api_ici
```

⚠️ **Ne JAMAIS commiter ce fichier sur GitHub.**

---

## 🌐 API REST

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/` | Interface web |
| `GET` | `/api/trading/<symbol>` | Données + indicateurs |
| `GET` | `/api/fundamental/<symbol>` | Fondamentales |
| `GET` | `/api/watchlist` | Prix actuels |
| `GET` | `/api/compare?symbols=AAPL,MSFT` | Comparateur |
| `GET` | `/api/export-csv/<symbol>` | Export CSV |

---

## 🛠️ Stack technique

| Couche | Technologie |
|--------|-------------|
| Backend | Python 3, Flask |
| Data | Twelve Data API |
| Indicateurs | NumPy, pandas |
| Frontend | HTML5, JavaScript |
| Charts | Lightweight Charts |

---

## ⚠️ Limitations

- **Twelve Data Free** : 800 crédits/jour, 8/minute
- **Latence 15 min** sur actions US (plan gratuit)
- **Indices** remplacés par ETF (SPY, DIA, QQQ)
- **Rate limit** : 12s minimum entre 2 appels

---

## 📝 Licence

MIT — Voir `LICENSE`

---

## ⭐ Si ce projet te plaît, mets une étoile !

---

