# ps1-to-ios

Kendi PS1 disk dökümünüzün **zip** dosyasını alır, oyunun kodunu
[psxrecomp](https://github.com/RetroPortingToolKit/psxrecomp) ile önceden C'ye
çevirir ve iPhone/iPad için **yerel, imzalı bir uygulama** üretir. Emülatör
ya da JIT kullanılmaz. Grafik, ses ve videolar çalışma anında telefondaki disk
imajından okunur.

> Bu repo oyun verisi içermez ve indirmez. Yalnızca sahip olduğunuz disklerin
> dökümleriyle kullanın. psxrecomp PolyForm Noncommercial 1.0.0 lisanslıdır:
> ürettiğiniz uygulamalar ticari olmayan kullanım içindir.

## Nasıl çalışır

```
game.zip ─► diski bul (cue/bin, chd, tek bin, iso; çok diskli setler)
        ─► SYSTEM.CNF → BOOT → PS-X EXE başlığı → seri no (ör. SCES-00891)
        ─► proje:  hazır profil varsa (profiles/<SERI>.json) o proje
                   yoksa psxrecomp'un kendi iskeleti (setup_project.sh)
        ─► oyunu diskten C'ye çevir (psxrecomp generate)
        ─► iOS katmanı (ios/): Belgeler klasörü, dokunmatik PS kumandası, MoltenVK
        ─► Xcode projesi → xcodebuild archive (otomatik imza) → .ipa
        ─► (isteğe bağlı) devicectl ile iPhone'a kur + diski Documents/disc/ içine kopyala
```

psxrecomp'un üç çalıştırma katmanı var: önceden derlenmiş kod, çalışma anında
derlenen overlay'ler ve her zaman doğru çalışan bir MIPS yorumlayıcısı. iOS
çalışma anında kod üretmeye izin vermediği için 2. katman kapatılır. Statik
geçişin bulamadığı kod yorumlayıcıda çalışır (iOS buna izin veriyor). Yani
**her oyun ilk derlemede doğru çalışmalı**. Hazır profili olan oyunlar ise
tamamen önceden derlendiği için daha hızlıdır.

| Proje türü | Oyunlar | Sonuç |
|---|---|---|
| Hazır (curated) | Hercules PAL: SCES-00891…00895 ([hercules-recompiled](https://github.com/obaidr1/hercules-recompiled)) | Tam AOT, modlar |
| Genel | Diğer tüm PS1 diskleri | Ana EXE derlenir, gerisi yorumlayıcıda; oyuna göre hız/uyumluluk değişir |

Yeni bir hazır proje eklemek için `profiles/<SERI>.json` yazmak yeterli
(repo, commit, proje klasörü, yamalar, GameData).

## Kullanım

Diski tanıma her yerde çalışır (Linux dahil):

```bash
python3 -m ps1ios inspect "Oyun.zip"
```

iPhone uygulamasını derlemek için bir Mac gerekir:

```bash
python3 -m ps1ios build "Oyun.zip" --team TAKIMID --human
```

Kurulum ve disk kopyası dahil:

```bash
python3 -m ps1ios build "Oyun.zip" --team TAKIMID --device <cihaz-id> --human
```

Cihaz kimliği:

```bash
xcrun devicectl list devices
```

Seçenekler: `--name` (ana ekran adı), `--bios SCPH1001.BIN` (isteğe bağlı;
yoksa OpenBIOS kullanılır), `--generic` (hazır profili yok say),
`--bundle-prefix`, `--work`, `--out`. `--human` verilmezse ilerleme
HookLink/NX2Apple'ın okuduğu JSON satırları olarak yazılır.

### Mac gereksinimleri

- Xcode (iOS SDK), Apple Developer takım kimliği (ücretsiz Personal Team de olur)
- `brew install cmake ninja git`, `pip3 install numpy pillow`
- LunarG Vulkan SDK (`glslc` + `MoltenVK.xcframework`), `VULKAN_SDK` ayarlı
- iPhone: iOS 16+, Geliştirici Modu açık

## Dosyalar

| Yol | Ne |
|---|---|
| `ps1ios/ingest.py` | Güvenli zip açma (zip-slip, link, boyut sınırı), disk bulma, eksik cue üretme, büyük/küçük harf düzeltme |
| `ps1ios/disc.py` | ISO9660 okuma, SYSTEM.CNF, BOOT, PS-X EXE başlığı, seri no ve bölge |
| `ps1ios/pipeline.py` | Hazır/genel proje, yamalar, generate, Xcode, imza, IPA, kurulum |
| `ios/` | iOS katmanı: `ios_platform.mm` (Belgeler klasörü, disk bulma, dokunmatik kumanda, AOT dışı derlemeyi kapatma), `ios.cmake`, `Info.plist.in`, psxrecomp yaması |
| `profiles/` | Hazır projeler |
| `tests/` | Sentetik disklerle birim testleri (oyun verisi yok) |

## Durum

- Doğrulanan: zip alma, disk tanıma, hazır/genel proje seçimi, CLI. Sentetik disklerle 10 test.
  psxrecomp yaması hem temiz psxrecomp'a (2a4824f) hem Hercules yamalı haline uygulanabiliyor.
- **Henüz doğrulanmayan:** Mac'te iOS derlemesi, imza ve cihazda çalışma.
  İlk Mac derlemesinde bakılacaklar: masaüstü OpenGL çizicisinin iOS'ta derlenip
  derlenmediği (derlenmezse iOS'ta kapatılır, Vulkan/MoltenVK ya da yazılımsal
  çizim kullanılır), SDL3'ün iOS açılışı, gömülü MoltenVK'nın yüklenmesi.
- Kare hızı oyunun kendi hızıyla sınırlı. Çoğu PS1 oyunu 30 ya da 60 Hz'de
  adım atar; port bunu artırmaz.
