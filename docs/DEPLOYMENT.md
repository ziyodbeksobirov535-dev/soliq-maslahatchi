# Serverga o'rnatish (PHASE 7)

Bu qo'llanma botni 24/7 ishlaydigan serverga qo'yishni oddiy qadamlar bilan tushuntiradi.
Bot va scheduler (RSS, hujjatlarni yangilash) **bitta jarayonda** ishlaydi. Baza — Supabase (PostgreSQL).

---

## 0. Narxlar taqqoslovi (2026-yil sentabr holatiga)

| Variant | Narx / oy | Resurs | Izoh |
|---|---|---|---|
| **Hetzner Cloud CX23** | ~€5.49 | 2 vCPU, 4 GB RAM, 40 GB | Eng arzon/kuchli nisbat. CX line vaqti-vaqti bilan "not available" bo'ladi — unda CPX/CAX tanlang |
| DigitalOcean Basic Droplet | $6 (1 GB) / $12 (2 GB) | 1 vCPU, 1–2 GB | 2026-01-01 dan sekundlik billing; boshqaruv paneli oson |
| Railway Hobby | $5 (+ $5 foydalanish krediti) | ~$20/vCPU, ~$10/GB RAM oyiga | PaaS: server boshqarish yo'q, lekin doimiy jarayon uchun $5 dan oshishi mumkin |
| Render Starter worker | $7 | 512 MB | Bepul "background worker" yo'q |
| **Supabase Free** | $0 | 500 MB DB | 7 kun faollik bo'lmasa **pauza**, avtomatik backup **yo'q** |
| Supabase Pro | $25 | 8 GB DB | Kunlik backup, pauza yo'q |

Manbalar: [Hetzner narxlari (costgoat)](https://costgoat.com/pricing/hetzner),
[bitdoze — Hetzner CX](https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/),
[DigitalOcean droplets](https://www.digitalocean.com/pricing/droplets),
[frontdeskreview — DO billing](https://frontdeskreview.com/software/vps-hosting/digitalocean/),
[Railway plans](https://docs.railway.com/pricing/plans),
[northflank — Railway vs Render](https://northflank.com/blog/railway-vs-render),
[Supabase pricing](https://supabase.com/pricing).
Narxlar o'zgaradi — xarid oldidan rasmiy sahifani tekshiring.

**Tavsiya:**
- Pilot: **Hetzner CX23 (yoki DO 2 GB) + Supabase Free** ≈ $6/oy. Bot har kuni bazaga murojaat qiladi,
  shuning uchun Supabase pauzaga tushmaydi. Backup'ni o'zimiz qilamiz (7-qadam).
- Production (haqiqiy foydalanuvchilar): **Supabase Pro ($25)** — kunlik backup va kafolat.
- RAM: kamida **2 GB**. Haftalik yangilash Soliq kodeksining ~6 MB HTML sahifasini parse qiladi.
  1 GB server olsangiz, swap qo'shing (2-qadam).
- Claude API xarajati alohida: console.anthropic.com → Billing (kredit + oylik limit qo'ying).

---

## 1. Server olish

1. Hetzner (yoki DigitalOcean) da ro'yxatdan o'ting.
2. Yangi server: **Ubuntu 24.04**, joylashuv — Yevropa (Germaniya/Finlyandiya; Supabase ham `eu-central-1`).
3. SSH kalit qo'shing (parol bilan kirishdan ko'ra xavfsiz).
4. Server IP manzilini yozib oling va kiring: `ssh root@SERVER_IP`

## 2. Serverni tayyorlash

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git postgresql-client curl
timedatectl set-timezone Asia/Tashkent

# Faqat SSH ochiq qolsin (bot Telegram'ga o'zi ulanadi, kirish porti kerak emas)
ufw allow OpenSSH && ufw --force enable

# Alohida foydalanuvchi (bot root bo'lib ishlamasin)
adduser --system --group --home /opt/soliq-maslahatchi soliq

# (Faqat 1 GB RAM bo'lsa) 2 GB swap
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Python 3.11+ kerak (`python3 --version`; Ubuntu 24.04 da 3.12 — mos).

Kodni yuklash:

```bash
cd /opt
git clone https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi.git soliq-maslahatchi-src
cp -a soliq-maslahatchi-src/. soliq-maslahatchi/ && rm -rf soliq-maslahatchi-src
cd /opt/soliq-maslahatchi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p .cache /opt/soliq-backups
chown -R soliq:soliq /opt/soliq-maslahatchi /opt/soliq-backups
```

Repo private bo'lsa: GitHub → Settings → Developer settings → Fine-grained token (faqat shu repo, read-only)
yoki serverga "deploy key" qo'shing.

## 3. Kalitlar va `.env`

```bash
cp .env.example .env
chown soliq:soliq .env && chmod 600 .env
nano .env
```

To'ldiriladigan qiymatlar (qo'shtirnoqsiz, bo'sh joysiz yozing):

| O'zgaruvchi | Qayerdan olinadi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram'da **@BotFather** → `/newbot` → nom va username → berilgan token |
| `ANTHROPIC_API_KEY` | **console.anthropic.com** → API Keys → Create Key. Chatda ko'rsatilgan eski kalitni **o'chirib (revoke)**, yangisini yarating. Billing'da kredit bo'lishi shart |
| `ANTHROPIC_MAIN_MODEL`, `ANTHROPIC_FAST_MODEL` | `.env.example` dagi qiymatlar qoladi |
| `SUPABASE_DB_URL` | Supabase Dashboard → loyiha `soliq-maslahatchi` → **Connect** → **Session pooler** URI (`postgresql://postgres.lxhpaappvrzxxqzafnct:[PAROL]@aws-...pooler.supabase.com:5432/postgres`). Parolni bilmasangiz: Project Settings → Database → Reset password |
| `SUPABASE_URL` | `https://lxhpaappvrzxxqzafnct.supabase.co` (ixtiyoriy) |
| `SUPABASE_SERVICE_ROLE_KEY` | Bot uchun **kerak emas** — bo'sh qoldiring |
| `ADMIN_TELEGRAM_IDS` | Sizning Telegram ID raqamingiz (**@userinfobot** ga yozing). Bir nechta bo'lsa vergul bilan |
| `DAILY_QUESTION_LIMIT` | Kunlik savol limiti (sukut 20) |
| `DISCOVERY_DAILY_LIMIT` | Lex.uz qidiruvida topilgan eski hujjatlardan kuniga nechtasi import qilinadi (`.env.example` da 50 — ~20 kunda ~1 000 hujjat, bazaga ~180 MB; 0 = o'chiq) |

Secret'larni hech qachon chatga, git'ga yoki skrinshotga qo'ymang. `.env` `.gitignore` da.

Tekshirish:

```bash
sudo -u soliq .venv/bin/python main.py --check          # sozlamalar to'liqmi
sudo -u soliq .venv/bin/python -m app.database.migrate --status   # 001–009 applied bo'lishi kerak
sudo -u soliq .venv/bin/python -m app.health            # baza ulanishi (rss hozircha ok:false bo'lishi normal)
```

Migratsiyalar Supabase'ga allaqachon qo'llangan. Keyinchalik yangi migratsiya qo'shilsa:
`sudo -u soliq .venv/bin/python -m app.database.migrate`.

## 4. Process manager (systemd) — bot doim ishlasin

```bash
cp deploy/soliq-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now soliq-bot
systemctl status soliq-bot
```

- Server qayta yoqilsa yoki bot yiqilsa — 10 soniyada avtomatik qayta ishga tushadi (`Restart=always`).
- To'xtatish/qayta ishga tushirish: `systemctl stop soliq-bot` / `systemctl restart soliq-bot`.
- Telegram'da botga `/start` yozing — javob kelsa, ishlayapti.

## 5. Scheduler

Alohida o'rnatish **kerak emas** — bot jarayoni ichida ishlaydi (Asia/Tashkent vaqti):

| Vaqt | Ish |
|---|---|
| har kuni 07:10 | Lex.uz RSS → soliq/biznesga oid yangiliklar (`/yangiliklar`) |
| har kuni 07:40 | Kuchga kirish sanasi kelgan hujjatlarni qayta tekshirish |
| yakshanba 03:20 | Kuzatiladigan hujjatlarni to'liq yangilash: 6 ta kodeks + RSS va qidiruvdan import qilinganlar (o'zgarishlar `ozgarishlar` jadvaliga) |
| shanba 04:10 | Lex.uz qidiruvi: amaldagi eski farmon/qaror/tartiblar ro'yxati (~90 so'rov, hujjatlar yuklanmaydi) |
| har kuni 08:10 | Topilgan hujjatlardan `DISCOVERY_DAILY_LIMIT` tasini import qilish (0 bo'lsa o'tkazib yuboriladi) |
| har 5 daqiqa | heartbeat fayli (health check uchun) |

Birinchi kuni yangiliklar bo'sh bo'lmasligi uchun RSS'ni qo'lda bir marta ishga tushiring:

```bash
sudo -u soliq .venv/bin/python -m app.collector.jobs rss
```

Qo'lda boshqa job'lar: `... -m app.collector.jobs future`, `... refresh`, `... discover`,
`... import-found --limit 20`.

## 6. Loglar

```bash
journalctl -u soliq-bot -f                 # jonli
journalctl -u soliq-bot --since "1 hour ago"
journalctl -u soliq-bot -p err --since today   # faqat xatolar
```

Loglarda token/kalitlar avtomatik yashiriladi. Disk to'lib qolmasligi uchun:
`/etc/systemd/journald.conf` da `SystemMaxUse=500M` qo'ying va `systemctl restart systemd-journald`.

## 7. Backup (zaxira nusxa)

Supabase Free'da avtomatik backup yo'q, shuning uchun har kuni `pg_dump`:

```bash
sudo -u soliq /opt/soliq-maslahatchi/deploy/backup.sh     # bir marta sinab ko'ring
crontab -u soliq -e
```

Qo'shiladigan satr (har kuni 02:30, 14 kun saqlanadi):

```
30 2 * * * /opt/soliq-maslahatchi/deploy/backup.sh >> /opt/soliq-backups/backup.log 2>&1
```

- Muhim: `pg_dump` versiyasi server versiyasidan (PostgreSQL 17) past bo'lmasin. Ubuntu'dagi `postgresql-client`
  eski bo'lsa: `apt install postgresql-client-17` (PGDG repozitoriyasi: https://www.postgresql.org/download/linux/ubuntu/).
- Zaxirani vaqti-vaqti bilan boshqa joyga ham ko'chiring (masalan, o'z kompyuteringizga `scp`).
- Tiklash: `pg_restore --clean --no-owner -d "$SUPABASE_DB_URL" /opt/soliq-backups/soliq-YYYYMMDD-HHMM.dump`.
- Supabase Pro'ga o'tsangiz, kunlik backup Supabase tomonidan ham qilinadi.

## 8. Health check

```bash
sudo -u soliq .venv/bin/python -m app.health --bot
```

JSON chiqaradi va muammo bo'lsa exit code 1 qaytaradi. Tekshiradi: baza ulanishi va hujjatlar soni,
oxirgi RSS 36 soatdan eski emasligi, bot heartbeat'i 15 daqiqadan eski emasligi.

Avtomatik (har 10 daqiqa; muammo bo'lsa `ADMIN_TELEGRAM_IDS` dagi birinchi adminga Telegram xabar):

```bash
crontab -u soliq -e
```

```
*/10 * * * * /opt/soliq-maslahatchi/deploy/healthcheck.sh >> /opt/soliq-maslahatchi/.cache/health.log 2>&1
```

Eslatma: admin avval botga `/start` yozgan bo'lishi kerak, aks holda Telegram xabar yuborishga ruxsat bermaydi.

## 9. Yangilash (yangi versiya chiqqanda)

```bash
cd /opt/soliq-maslahatchi
sudo -u soliq git pull
sudo -u soliq .venv/bin/pip install -r requirements.txt
sudo -u soliq .venv/bin/python -m app.database.migrate
systemctl restart soliq-bot
journalctl -u soliq-bot -n 50
```

## 10. Muammolar

| Belgi | Sabab / yechim |
|---|---|
| Bot javob bermaydi | `systemctl status soliq-bot`, `journalctl -u soliq-bot -n 100` |
| "Savol-javob hali sozlanmagan" | `ANTHROPIC_API_KEY` bo'sh yoki kredit tugagan (console.anthropic.com → Billing) |
| `TelegramConflictError` | Bot boshqa joyda ham ishlayapti (bitta token — bitta jarayon) |
| Baza ulanmaydi | `SUPABASE_DB_URL` (Session pooler, parol); Supabase loyihasi pauzada emasligini Dashboard'da tekshiring |
| Health: `rss` ok:false | Birinchi kunlarda normal; 7:10 dan keyin ham bo'lsa — `journalctl ... | grep rss_job` |
| Xotira yetmaydi (OOM) | Swap qo'shing yoki 2–4 GB serverga o'ting |
