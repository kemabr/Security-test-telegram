import os
import asyncio
import aiohttp
import time
import statistics
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
active_tests = {}

async def get_token(session, base_url, username, password):
    """Marzban'dan JWT token al"""
    login_url = f"{base_url}/api/admin/token"
    
    try:
        data = {'username': username, 'password': password}
        
        async with session.post(
            login_url, 
            data=data, 
            timeout=aiohttp.ClientTimeout(total=10), 
            ssl=False
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                return result.get('access_token'), None
            else:
                text = await resp.text()
                return None, f"HTTP {resp.status}: {text[:100]}"
                
    except Exception as e:
        return None, str(e)[:100]

async def heavy_api_request(session, url, token, results):
    """Ağır API isteği - veritabanını zorlar"""
    req_start = time.time()
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with session.get(
            url, 
            headers=headers, 
            timeout=timeout, 
            ssl=False
        ) as resp:
            body = await resp.read()
            elapsed = (time.time() - req_start) * 1000
            
            results['total'] += 1
            results['status_codes'][resp.status] = results['status_codes'].get(resp.status, 0) + 1
            
            if resp.status == 200:
                results['success'] += 1
                results['times'].append(elapsed)
                results['bytes_received'] += len(body)
            else:
                results['failed'] += 1
                
    except Exception as e:
        results['total'] += 1
        results['failed'] += 1
        err = str(e)[:60]
        if len(results['errors']) < 5:
            results['errors'].append(err)

async def api_worker(session, url, token, end_time, results, semaphore):
    """Sürekli ağır istek"""
    while time.time() < end_time:
        async with semaphore:
            await heavy_api_request(session, url, token, results)
        # Minimum bekleme - maksimum yük
        await asyncio.sleep(0.01)

async def run_api_test(base_url, endpoint, username, password, threads, duration, rampup):
    """Gerçek API testi"""
    
    results = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'times': [],
        'status_codes': {},
        'errors': [],
        'bytes_received': 0
    }
    
    connector = aiohttp.TCPConnector(
        limit=threads * 5, 
        limit_per_host=threads * 3,
        ttl_dns_cache=300,
        use_dns_cache=True,
    )
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # LOGIN
        token, error = await get_token(session, base_url, username, password)
        if not token:
            return None, f"❌ Login başarısız: {error}"
        
        # API TEST
        target_url = f"{base_url}{endpoint}"
        start_time = time.time()
        end_time = start_time + duration
        
        semaphore = asyncio.Semaphore(threads)
        tasks = []
        
        for i in range(threads):
            task = asyncio.create_task(
                api_worker(session, target_url, token, end_time, results, semaphore)
            )
            tasks.append(task)
            
            if i < threads - 1 and rampup > 0:
                await asyncio.sleep(rampup / threads)
        
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=duration + 30
            )
        except asyncio.TimeoutError:
            pass
        
        elapsed = time.time() - start_time
        return results, elapsed

def format_results(results, elapsed, target):
    """Sonuçları formatla"""
    
    if results is None:
        return f"❌ Test başarısız: {target}"
    
    if not results['times']:
        errors = "\n".join(f"├ `{e}`" for e in results['errors'][:3]) if results['errors'] else "Bilinmeyen hata"
        return f"❌ Sonuç alınamadı.\n\n**Hatalar:**\n{errors}"
    
    times = results['times']
    total = results['total']
    success = results['success']
    failed = results['failed']
    
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)
    
    sorted_times = sorted(times)
    p95 = sorted_times[int(len(sorted_times) * 0.95)]
    p99 = sorted_times[int(len(sorted_times) * 0.99)]
    
    error_rate = (failed / total * 100) if total > 0 else 0
    rps = round(total / elapsed, 2) if elapsed > 0 else 0
    mb_received = round(results['bytes_received'] / (1024*1024), 2)
    
    status_str = ""
    for code, count in sorted(results['status_codes'].items()):
        status_str += f"\n├ HTTP {code}: {count}"
    
    error_str = ""
    if results['errors']:
        unique = list(dict.fromkeys(results['errors']))[:3]
        error_str = "\n\n⚠️ **Örnek Hatalar**\n" + "\n".join(f"├ `{e}`" for e in unique)
    
    # Yük değerlendirmesi
    load_status = "🟢 Normal"
    if avg_time > 500:
        load_status = "🟡 Yavaş"
    if avg_time > 1000:
        load_status = "🟠 Ağır"
    if avg_time > 2000:
        load_status = "🔴 Kritik"
    if error_rate > 5:
        load_status = "💀 Çöküş"
    
    return (
        f"🔥 **GERÇEK API TEST SONUÇLARI**\n"
        f"📊 Yük Durumu: {load_status}\n\n"
        f"🌐 Hedef: `{target}`\n"
        f"⏱️ Süre: {round(elapsed, 1)} sn\n"
        f"🚀 RPS: {rps}\n"
        f"📦 Veri: {mb_received} MB\n\n"
        f"📈 **İstatistikler**\n"
        f"├ Toplam: {total}\n"
        f"├ ✅ Başarılı: {success}\n"
        f"├ ❌ Başarısız: {failed}\n"
        f"├ 📉 Hata: %{round(error_rate, 2)}{status_str}\n\n"
        f"⏱️ **Yanıt Süreleri (ms)**\n"
        f"├ Ort: {round(avg_time, 1)}\n"
        f"├ Min: {round(min_time, 1)}\n"
        f"├ Max: {round(max_time, 1)}\n"
        f"├ P95: {round(p95, 1)}\n"
        f"├ P99: {round(p99, 1)}"
        f"{error_str}"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 **Load Test Bot v5 - AĞIR YÜK**\n\n"
        "**Komutlar:**\n\n"
        "`/test site.com [thread] [sure] [rampup]`\n"
        "→ Basit HTTP testi\n\n"
        "`/api site.com:port /endpoint kullanici sifre [thread] [sure] [rampup]`\n"
        "→ **Login + Token + Ağır API testi**\n\n"
        "**Örnek:**\n"
        "`/api vipsecure.dev:448 /api/users admin sifre 100 60 15`",
        parse_mode='Markdown'
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if active_tests.get(chat_id):
        await update.message.reply_text("⏳ Zaten test çalışıyor!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ `/test site.com [thread] [sure] [rampup]`",
            parse_mode='Markdown'
        )
        return
    
    target = args[0]
    threads = min(int(args[1]) if len(args) > 1 else 10, 1000)
    duration = min(int(args[2]) if len(args) > 2 else 30, 300)
    rampup = int(args[3]) if len(args) > 3 else 5
    
    active_tests[chat_id] = True
    
    msg = await update.message.reply_text(
        f"🚀 **HTTP Test**\n\n"
        f"🌐 `{target}`\n"
        f"👥 {threads} | ⏱️ {duration}s | 📈 {rampup}s\n\n"
        f"⏳ Çalışıyor...",
        parse_mode='Markdown'
    )
    
    try:
        # Basit HTTP test
        results = {
            'total': 0, 'success': 0, 'failed': 0,
            'times': [], 'status_codes': {}, 'errors': [],
            'bytes_received': 0
        }
        
        if not target.startswith(('http://', 'https://')):
            url = f'https://{target}'
        else:
            url = target
        
        connector = aiohttp.TCPConnector(limit=threads * 3)
        async with aiohttp.ClientSession(connector=connector) as session:
            start_time = time.time()
            end_time = start_time + duration
            
            semaphore = asyncio.Semaphore(threads)
            tasks = []
            
            for i in range(threads):
                task = asyncio.create_task(
                    simple_worker(session, url, end_time, results, semaphore)
                )
                tasks.append(task)
                if i < threads - 1 and rampup > 0:
                    await asyncio.sleep(rampup / threads)
            
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=duration + 15
                )
            except asyncio.TimeoutError:
                pass
            
            elapsed = time.time() - start_time
        
        report = format_results(results, elapsed, target)
        await msg.edit_text(report, parse_mode='Markdown')
        
    except Exception as e:
        await msg.edit_text(f"❌ Hata: {str(e)[:200]}")
    finally:
        active_tests[chat_id] = False

async def simple_worker(session, url, end_time, results, semaphore):
    while time.time() < end_time:
        async with semaphore:
            req_start = time.time()
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
                    body = await resp.read()
                    elapsed = (time.time() - req_start) * 1000
                    
                    results['total'] += 1
                    results['status_codes'][resp.status] = results['status_codes'].get(resp.status, 0) + 1
                    
                    if resp.status == 200:
                        results['success'] += 1
                        results['times'].append(elapsed)
                        results['bytes_received'] += len(body)
                    else:
                        results['failed'] += 1
                        
            except Exception as e:
                results['total'] += 1
                results['failed'] += 1
                if len(results['errors']) < 5:
                    results['errors'].append(str(e)[:60])
        
        await asyncio.sleep(0.05)

async def api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerçek API testi - login + token + ağır yük"""
    chat_id = update.effective_chat.id
    
    if active_tests.get(chat_id):
        await update.message.reply_text("⏳ Zaten test çalışıyor!")
        return
    
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Kullanım:\n"
            "`/api site.com:port /endpoint kullanici sifre [thread] [sure] [rampup]`\n\n"
            "Örnek:\n"
            "`/api vipsecure.dev:448 /api/users admin sifre123 100 60 15`",
            parse_mode='Markdown'
        )
        return
    
    host_port = args[0]
    endpoint = args[1]
    username = args[2]
    password = args[3]
    
    threads = min(int(args[4]) if len(args) > 4 else 10, 500)
    duration = min(int(args[5]) if len(args) > 5 else 30, 300)
    rampup = int(args[6]) if len(args) > 6 else 5
    
    if ':' in host_port:
        host, port = host_port.split(':')
        base_url = f"https://{host}:{port}"
    else:
        base_url = f"https://{host_port}"
    
    target = f"{base_url}{endpoint}"
    
    active_tests[chat_id] = True
    
    msg = await update.message.reply_text(
        f"🔥 **AĞIR API TESTİ**\n\n"
        f"🌐 `{target}`\n"
        f"👤 Kullanıcı: `{username}`\n"
        f"👥 Thread: {threads} | ⏱️ {duration}s | 📈 {rampup}s\n\n"
        f"⚠️ Bu test gerçekten backend'i zorlar!\n"
        f"🔐 Login yapılıyor...",
        parse_mode='Markdown'
    )
    
    try:
        results, elapsed = await run_api_test(
            base_url, endpoint, username, password, 
            threads, duration, rampup
        )
        report = format_results(results, elapsed, target)
        await msg.edit_text(report, parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"❌ Hata: {str(e)[:200]}")
    finally:
        active_tests[chat_id] = False

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("api", api_command))
    print("🤖 Bot v5 başladı - Ağır yük modu aktif")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
