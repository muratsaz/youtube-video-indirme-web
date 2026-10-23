# cep. — YouTube indirme uygulaması

Türkçe arayüzlü, yalnızca bilgisayarınızda çalışan web uygulaması.

## Açmak için

**Baslat.vbs** dosyasına çift tıklayın. Tarayıcı otomatik açılır.
Alternatif olarak **Baslat.cmd** dosyasını kullanabilirsiniz; bu seçenek uygulama çalışırken açık kalacak bir konsol gösterir.

1. YouTube bağlantısını yapıştırın.
2. İsterseniz video kalitesini veya MP3 seçeneğini değiştirin.
3. **İndirmeyi başlat** düğmesine basın.

Dosyalar otomatik olarak kullanıcı klasörünüzün `Downloads/YouTube` dizinine kaydedilir. “Klasörü aç” düğmesiyle ulaşabilirsiniz. Aynı dosyayı tarayıcıdan tekrar kaydetmeniz gerekmez. Sayfayı kapatsanız da uygulama arka planda çalışmayı sürdürür. Tamamen kapatmak için **Durdur.cmd** dosyasını çalıştırın; devam eden indirmeler iptal edilir. Bilgisayar kapanırsa yarıda kalan indirmeleri yeniden açınca geçmişten “Yeniden dene” düğmesiyle başlatabilirsiniz.

## Özellikler

- MP4 video: en fazla 360p, 720p, 1080p veya mevcut en yüksek kalite (4K dahil).
- Seçilen çözünürlük yoksa mevcut en iyi alt çözünürlük.
- MP3 ses: 192 kbps (kaynak ses kalitesini artırmaz).
- Tek bağlantı ile indirme; normal video, Shorts ve kısa paylaşım bağlantıları.
- Sıralı indirme kuyruğu, ilerleme, iptal ve yeniden deneme.
- Uygulama yeniden açılsa da saklanan indirme geçmişi.

Canlı yayınlar, oynatma listeleri ve erişim/oturum gerektiren videolar desteklenmez. YouTube bazen erişilebilir videolarda da doğrulama isteyebilir veya indirmeyi engelleyebilir. Yalnızca indirme hakkınız olan içeriklerde kullanın.

## Kurulum ve bakım

Windows bilgisayarınızda Python 3.11+, Node.js 22+ ve FFmpeg'in kurulu ve PATH içinde olması gerekir. Python yükleyicisinde “Add Python to PATH” seçeneğini etkinleştirin.

1. GitHub'da **Code → Download ZIP** ile projeyi indirin ve ZIP dosyasını bir klasöre çıkarın; Git kullanıyorsanız depoyu klonlayabilirsiniz.
2. **Baslat.cmd** dosyasına çift tıklayın. İlk açılışta Python ortamı oluşturulur ve gerekli paketler internetten kurulur.
3. Tarayıcı açıldıktan sonra YouTube bağlantısını yapıştırıp indirmeyi başlatın. Sonraki açılışlarda **Baslat.vbs** dosyasını kullanabilirsiniz.

Ayrıntılı kurulum adımları ve gerekli araçları kurma komutları [KURULUM.txt](KURULUM.txt) dosyasındadır.

İndirmeler YouTube değişiklikleri nedeniyle çalışmazsa **Guncelle.cmd** dosyasını çalıştırın. Uygulama kapatılır, indirme motoru güncellenir ve uygulama yeniden açılır. Devam eden indirmeler iptal edilir. Konsol üzerinden başlatılan uygulama Ctrl+C ile de durdurulabilir.

Uygulama yalnızca `127.0.0.1` üzerinde çalışır; internette yayımlanmaz. Başlangıç adresi `http://127.0.0.1:8765` olur. Bu adres başka bir uygulamadaysa 8774'e kadar boş port arar. İkinci açılış mevcut uygulamayı kullanır.

İndirme motoru: [yt-dlp](https://github.com/yt-dlp/yt-dlp). Node.js ve EJS kurulumu [resmî yönergelere](https://github.com/yt-dlp/yt-dlp/wiki/EJS) göre yapılmıştır. Geçmiş ve hata kayıtları `.data/` klasöründedir. Çerezler veya YouTube hesabı kullanılmaz.

## Geliştirme

`.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765`

Testler için: `.venv/Scripts/python.exe -m pip install httpx` ardından `.venv/Scripts/python.exe -m unittest discover -s tests -v`.

Otomatik testler, YouTube'a bağlanmadan URL doğrulamasını, erişim kontrollerini, kuyruk yönetimini, iptal ve dosya kaydını denetler. Canlı YouTube erişimi ağ ve YouTube kısıtlamalarına bağlıdır.
