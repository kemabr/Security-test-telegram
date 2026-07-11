import os
import subprocess
import tempfile
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

def create_jmx_file(target_url, threads, duration, rampup):
    """JMeter test planı oluşturur"""
    
    # URL parsing
    if not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url
    
    # Domain ve path ayırma
    from urllib.parse import urlparse
    parsed = urlparse(target_url)
    domain = parsed.netloc
    protocol = parsed.scheme
    path = parsed.path if parsed.path else '/'
    
    jmx = f'''<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Load Test">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments">
        <collectionProp name="Arguments.arguments"/>
      </elementProp>
      <stringProp name="TestPlan.comments"></stringProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="{threads} Users">
        <intProp name="ThreadGroup.num_threads">{threads}</intProp>
        <intProp name="ThreadGroup.ramp_time">{rampup}</intProp>
        <longProp name="ThreadGroup.duration">{duration * 1000}</longProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
      </ThreadGroup>
      <hashTree>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="HTTP Request">
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
            <collectionProp name="Arguments.arguments"/>
          </elementProp>
          <stringProp name="HTTPSampler.domain">{domain}</stringProp>
          <stringProp name="HTTPSampler.port"></stringProp>
          <stringProp name="HTTPSampler.protocol">{protocol}</stringProp>
          <stringProp name="HTTPSampler.path">{path}</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
          <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
          <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
        </HTTPSamplerProxy>
        <hashTree>
          <ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="Summary Report">
            <boolProp name="ResultCollector.error_logging">false</boolProp>
            <objProp>
              <name>saveConfig</name>
              <value class="SampleSaveConfiguration">
                <time>true</time>
                <latency>true</latency>
                <timestamp>true</timestamp>
                <success>true</success>
                <label>true</label>
                <code>true</code>
                <message>true</message>
                <threadName>true</threadName>
                <dataType>true</dataType>
                <encoding>false</encoding>
                <assertions>true</assertions>
                <subresults>true</subresults>
                <responseData>false</responseData>
                <samplerData>false</samplerData>
                <xml>false</xml>
                <fieldNames>true</fieldNames>
                <responseHeaders>false</responseHeaders>
                <requestHeaders>false</requestHeaders>
                <responseDataOnError>false</responseDataOnError>
                <saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
                <assertionsResultsToSave>0</assertionsResultsToSave>
                <bytes>true</bytes>
                <sentBytes>true</sentBytes>
                <url>true</url>
                <threadCounts>true</threadCounts>
                <idleTime>true</idleTime>
                <connectTime>true</connectTime>
              </value>
            </objProp>
            <stringProp name="filename"></stringProp>
          </ResultCollector>
        </hashTree>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>'''
    return jmx

def run_jmeter_test(jmx_path, jtl_path):
    """JMeter CLI çalıştırır"""
    cmd = [
        'jmeter', '-n', '-t', jmx_path,
        '-l', jtl_path,
        '-j', '/tmp/jmeter.log'
    ]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300  # 5 dakika timeout
    )
    return result

def parse_results(jtl_path):
    """JTL sonuçlarını analiz eder"""
    total = 0
    success = 0
    failed = 0
    times = []
    
    try:
        with open(jtl_path, 'r') as f:
            lines = f.readlines()
            
        # İlk satır header
        for line in lines[1:]:
            parts = line.strip().split(',')
            if len(parts) >= 8:
                total += 1
                success_flag = parts[7].strip().lower()
                if success_flag == 'true':
                    success += 1
                else:
                    failed += 1
                
                # Response time (column 1)
                try:
                    times.append(int(parts[1]))
                except:
                    pass
    except Exception as e:
        return None, str(e)
    
    if not times:
        return None, "Sonuç bulunamadı"
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    # Percentile hesaplama
    sorted_times = sorted(times)
    p95_idx = int(len(sorted_times) * 0.95)
    p99_idx = int(len(sorted_times) * 0.99)
    p95 = sorted_times[min(p95_idx, len(sorted_times)-1)]
    p99 = sorted_times[min(p99_idx, len(sorted_times)-1)]
    
    results = {
        'total': total,
        'success': success,
        'failed': failed,
        'avg_time': round(avg_time, 2),
        'min_time': min_time,
        'max_time': max_time,
        'p95': p95,
        'p99': p99,
        'error_rate': round((failed/total)*100, 2) if total > 0 else 0
    }
    
    return results, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 **JMeter Load Test Bot**\n\n"
        "Komutlar:\n"
        "`/test site.com [kullanici] [sure_sn] [rampup_sn]`\n\n"
        "Örnek:\n"
        "`/test google.com 50 30 10`\n"
        "→ 50 kullanıcı, 30 saniye, 10 saniye ramp-up\n\n"
        "Varsayılan: 10 kullanıcı, 30 saniye, 5 saniye ramp-up",
        parse_mode='Markdown'
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Argüman parsing
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
    
    # Limitler (Railway kaynakları için)
    if threads > 500:
        await update.message.reply_text("❌ Maksimum 500 kullanıcı!")
        return
    if duration > 300:
        await update.message.reply_text("❌ Maksimum 300 saniye (5 dk)!")
        return
    
    await update.message.reply_text(
        f"🚀 **Test Başlıyor**\n\n"
        f"🌐 Hedef: `{target}`\n"
        f"👥 Kullanıcı: {threads}\n"
        f"⏱️ Süre: {duration} sn\n"
        f"📈 Ramp-up: {rampup} sn\n\n"
        f"⏳ Lütfen bekleyin...",
        parse_mode='Markdown'
    )
    
    try:
        # Geçici dosyalar
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jmx', delete=False) as f:
            jmx_path = f.name
            f.write(create_jmx_file(target, threads, duration, rampup))
        
        jtl_path = f"/tmp/result_{int(time.time())}.jtl"
        
        # JMeter çalıştır
        start_time = time.time()
        result = run_jmeter_test(jmx_path, jtl_path)
        elapsed = round(time.time() - start_time, 2)
        
        if result.returncode != 0:
            error_msg = result.stderr[-1000:] if result.stderr else "Bilinmeyen hata"
            await update.message.reply_text(
                f"❌ **JMeter Hatası**\n```\n{error_msg}\n```",
                parse_mode='Markdown'
            )
            return
        
        # Sonuçları parse et
        results, error = parse_results(jtl_path)
        
        if error:
            await update.message.reply_text(f"❌ Sonuç analiz hatası: {error}")
            return
        
        # Rapor oluştur
        report = (
            f"📊 **Test Sonuçları**\n\n"
            f"🌐 Hedef: `{target}`\n"
            f"⏱️ Test Süresi: {elapsed} sn\n\n"
            f"📈 **İstatistikler**\n"
            f"├ Toplam İstek: {results['total']}\n"
            f"├ ✅ Başarılı: {results['success']}\n"
            f"├ ❌ Başarısız: {results['failed']}\n"
            f"├ 📉 Hata Oranı: %{results['error_rate']}\n\n"
            f"⏱️ **Yanıt Süreleri (ms)**\n"
            f"├ Ortalama: {results['avg_time']}\n"
            f"├ Minimum: {results['min_time']}\n"
            f"├ Maksimum: {results['max_time']}\n"
            f"├ P95: {results['p95']}\n"
            f"├ P99: {results['p99']}"
        )
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏱️ Test zaman aşımına uğradı (5 dk)!")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {str(e)}")
    finally:
        # Temizlik
        for f in [jmx_path, jtl_path]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    
    # Railway webhook
    PORT = int(os.getenv("PORT", 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
