import os
import asyncio
import aiohttp
import time
import statistics
from collections import deque
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

# Global test durumu
active_tests = {}

async def run_load_test(target, threads, duration, rampup, chat_id):
    """Gerçek async load test - JMeter yerine"""
    
    results = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'times': [],
        'status_codes': {},
        'errors': deque(maxlen=10)
    }
    
    start_time = time.time()
    semaphore = asyncio.Semaphore(threads)
    
    async def fetch(session, url):
        async with semaphore:
            req_start = time.time()
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, timeout=timeout, ssl=False) as resp:
                    await resp.read()
                    elapsed = (time.time() - req_start) * 1000  # ms
                    
                    results['total'] += 1
                    results['success'] += 1
                    results['times'].append(elapsed)
                    
                    code = resp.status
                    results['status_codes'][code] = results['status_codes'].get(code, 0) + 1
                    
            except Exception as e:
                results['total'] += 1
                results['failed'] += 1
                error_str = str(e)[:50]
                results['errors'].append(error_str)
    
    # URL hazırla
    if not target.startswith(('http://', 'https://')):
        url = f'https://{target}'
    else:
        url = target
    
    # Ramp-up: kullanıcıları yavaş yavaş başlat
    connector = aiohttp.TCPConnector(limit=threads * 2, limit_per_host=threads)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        end_time = time.time() + duration
        
        # Her saniye yeni kullanıcı ekle (ramp-up)
        users_per_second = threads / max(rampup, 1)
        current_users = 0
        
        while time.time() < end_time and current_users < threads:
            # Her iterasyonda birkaç kullanıcı ekle
            to_add = min(int(users_per_second) + 1, threads - current_users)
            
            for _ in range(to_add):
                task = asyncio.create_task(
                    worker(session, url, end_time, results, semaphore)
                )
                tasks.append(task)
            
            current_users += to_add
            await asyncio.sleep(1)
        
        # Kalan süre boyunca bekleyip tamamla
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    return results, time.time() - start_time

async def worker(session, url, end_time, results, semaphore):
    """Tek bir sanal kullanıcı"""
    while time.time() < end_time:
        async with semaphore:
            req_start = time.time()
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, timeout=timeout, ssl=False) as resp:
                    await resp.read()
                    elapsed = (time.time() - req_start) * 1000
                    
                    results['total'] += 1
                    results['success'] += 1
                    results['times'].append(elapsed)
                    
                    code = resp.status
                    results['status_codes'][code] = results['status_codes'].get(code, 0) + 1
                    
            except Exception as e:
                results['total'] += 1
                results['failed'] += 1
                error_str = str(e)[:50]
                if len(results['errors']) < 10:
                    results['errors'].append(error_str)
        
        # Küçük bekleme (doğal davranış)
        await asyncio.sleep(0.1)

def format_results(results, elapsed, target):
    """Sonuçları formatla"""
    
    if not results['times']:
        return "❌ Test tamamlandı ama sonuç alınamadı. Site erişilebilir mi?"
    
    times = results['times']
    total = results['total']
    success = results['success']
    failed = results['failed']
    
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)
    
    # Percentile
    sorted_times = sorted(times)
    p95_idx = int(len(sorted_times) * 0.95)
    p99_idx = int(len(sorted_times) * 0.99)
    p95 = sorted_times[min(p95_idx, len(sorted_times)-1)]
    p99 = sorted_times[min(p99_idx, len(sorted_times)-1)]
    
    error_rate = (failed / total * 100) if total > 0 else 0
    
    # RPS hesapla
    rps = round(total / elapsed, 2) if elapsed > 0 else 0
    
    # Status codes
    status_str = ""
    for code, count in sorted(results['status_codes'].items()):
        status_str += f"\n├ HTTP {code}: {count}"
    
    # Hatalar
    error_str = ""
    if results['errors']:
        unique_errors = list(dict.fromkeys(results['errors']))[:3]
        error_str = "\n\n⚠️ **Örnek Hatalar**\n" + "\n".join(f"├ `{e}`" for e in unique_errors)
    
    report = (
        f"📊 **Test Sonuçları**\n\n"
        f"🌐 Hedef: `{target}`\n"
        f"⏱️ Test Süresi: {round(elapsed, 1)} sn\n"
        f"🚀 RPS (İstek/Sn): {rps}\n\n"
        f"📈 **İstatistikler**\n"
        f"├ Toplam İstek: {total}\n"
        f"├ ✅ Başarılı: {success}\n"
        f"├ ❌ Başarısız: {failed}\n"
        f"├ 📉 Hata Oranı: %{round(error_rate, 2)}\n"
        f"├ 📊 Status Kodları:{status_str}\n\n"
        f"⏱️ **Yanıt Süreleri (ms)**\n"
        f"├ Ortalama: {round(avg_time, 2)}\n"
        f"├ Minimum: {round(min_time, 2)}\n"
        f"├ Maksimum: {round(max_time, 2)}\n"
        f"├ P95: {round(p95, 2)}\n"
        f"├ P99: {round(p99, 2)}"
        f"{error_str}"
    )
    
    return report

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 **Load Test Bot**\n\n"
        "Komutlar:\n"
        "`/test site.com [kullanici] [sure_sn] [rampup_sn]`\n\n"
        "Örnek:\n"
        "`/test httpbin.org 50 30 10`\n"
        "→ 50 kullanıcı, 30 saniye, 10 saniye ramp-up\n\n"
        "Varsayılan: 10 kullanıcı, 30 saniye, 5 saniye ramp-up\n\n"
        "⚡ JMeter yerine Python asyncio ile çalışır - çok daha hızlı!",
        parse_mode='Markdown'
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Aktif test var mı kontrol et
    if chat_id in active_tests and active_tests[chat_id]:
        await update.message.reply_text("⏳ Zaten bir test çalışıyor, lütfen bekleyin!")
        return
    
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "❌ Hedef site belirtin!\n"
            "Kullanım: `/test site.com [kullanici] [sure] [rampup]`",
            parse_mode='Markdown'
        )
        return
    
    target = args[0]
    threads = int(args[1]) if len(args) > 1 else 10
    duration = int(args[2]) if len(args) > 2 else 30
    rampup = int(args[3]) if len(args) > 3 else 5
    
    # Limitler
    if threads > 1000:
        await update.message.reply_text("❌ Maksimum 1000 kullanıcı!")
        return
    if duration > 300:
        await update.message.reply_text("❌ Maksimum 300 saniye (5 dk)!")
        return
    if rampup > duration:
        await update.message.reply_text("❌ Ramp-up süresi test süresinden uzun olamaz!")
        return
    
    # Test başlat
    active_tests[chat_id] = True
    
    msg = await update.message.reply_text(
        f"🚀 **Test Başlıyor**\n\n"
        f"🌐 Hedef: `{target}`\n"
        f"👥 Kullanıcı: {threads}\n"
        f"⏱️ Süre: {duration} sn\n"
        f"📈 Ramp-up: {rampup} sn\n\n"
        f"⏳ Test çalışıyor...",
        parse_mode='Markdown'
    )
    
    try:
        results, elapsed = await run_load_test(target, threads, duration, rampup, chat_id)
        
        report = format_results(results, elapsed, target)
        
        await msg.edit_text(report, parse_mode='Markdown')
        
    except Exception as e:
        await msg.edit_text(f"❌ Test hatası: {str(e)}")
    finally:
        active_tests[chat_id] = False

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    
    print("🤖 Bot başlıyor...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
        
