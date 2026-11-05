# Invoice Automation

Aplikasi desktop Windows untuk membagi qty RAB ke sejumlah kendaraan per termin,
lalu mengekspor invoice Excel per kendaraan mengikuti layout
`invoice_template.xlsx`.

Aplikasi berjalan **offline**, data disimpan lokal di SQLite, dan tidak memerlukan
koneksi internet. Dibangun dengan Python, PySide6, openpyxl, dan SQLite.

## Fitur

- Proyek lokal: data klien, prefix No PO, tipe kendaraan default, tanggal invoice.
- Import RAB dari Excel dengan **deteksi header otomatis** dan dialog koreksi
  pemetaan kolom (nama barang, satuan, harga, qty total, kolom termin).
- Mendukung RAB **banyak jenis kendaraan** dalam satu sheet. Setiap blok
  `NAMA JENIS (N Unit)` menjadi kelompok item + slot unit sendiri.
- Import daftar plat dari Excel atau isi langsung di tabel kendaraan. Plat boleh
  dikosongkan sementara; invoice memakai label `JENIS #unit`.
- Validasi total qty semua termin = qty RAB per item.
- Pembagian otomatis per item per termin, per jenis kendaraan:
  - habis dibagi → langsung rata;
  - ada sisa → antrean konfirmasi untuk memilih kendaraan penerima tambahan 1;
  - saran awal memprioritaskan kendaraan yang paling sedikit menerima item
    tersebut di termin sebelumnya.
- Edit qty alokasi manual langsung di matriks item × kendaraan; pilih jenis
  kendaraan lewat dropdown.
- Kunci termin; export diblokir jika masih ada selisih qty.
- Pelacakan sisa volume yang belum dialokasikan.
- Export invoice Excel per plat per termin, atau satu workbook berisi banyak sheet.
- Riwayat aktivitas (import, alokasi otomatis, kunci, export, dll.).
- Template invoice dapat diganti lewat menu **Pengaturan**.

## Instalasi & Menjalankan

Prasyarat: Python 3.10+ (diuji dengan Python 3.13).

```bat
pip install -r requirements.txt
python main.py
```

Atau klik dua kali `run.bat`. Script itu akan membuat virtual environment
`.venv`, memasang dependensi, lalu menjalankan aplikasi tanpa jendela konsol.

## Alur Pemakaian

1. **Buat proyek** dari sidebar, lalu lengkapi informasi proyek di tab
   **1. Data Proyek**.
2. **Import RAB** (tombol `Import RAB`):
   - pilih file `.xlsx`;
   - periksa sheet, baris header, dan peran kolom di dialog pemetaan;
   - klik `Lanjut`, periksa ringkasan, lalu `Import RAB`.
3. **Import RAB** akan otomatis membuat jenis kendaraan dan slot unit sesuai
   penanda `(N Unit)` di RAB. Plat boleh dibiarkan kosong dulu, lalu diisi lewat
   tabel kendaraan atau `Import Plat Excel`.
4. Buka tab **2. Alokasi Termin**, pilih termin dan jenis kendaraan, lalu klik
   `Bagi Otomatis`. Item dengan sisa akan memunculkan antrean konfirmasi.
   `Bagi Otomatis` memproses semua jenis kendaraan pada termin tersebut.
5. Setelah semua item di semua jenis seimbang, klik `Kunci Termin`.
6. Buka tab **3. Export Invoice**, pilih kendaraan, folder output, dan format.
   Klik `Export Invoice`.

## Format Excel RAB

Format tidak dikunci mati. Aplikasi mendeteksi header, dan jika meleset kamu bisa
mengoreksi peran tiap kolom.

### RAB multi-jenis kendaraan

Format ini didukung langsung (contoh: `sample/rab_sample_real.xlsx`):

| No | Uraian Pekerjaan | Satuan | Volume | Harga Satuan | Jumlah Biaya | … | Termin 1 Volume | Termin 2 Volume |
|----|------------------|--------|--------|--------------|--------------|---|-----------------|-----------------|
| A  | YAMAHA VIXION (3 Unit) | | | | | | | |
| 1  | Service | UNIT | 6 | 240000 | 1440000 | | 3 | 3 |
| 2  | Oli Mesin | LITER | 6 | 100000 | 600000 | | 3 | 3 |
| B  | YAMAHA SCORPIO (8 Unit) | | | | | | | |
| 1  | Service | UNIT | 16 | 240000 | 3840000 | | 8 | 8 |

Ketentuan format ini:

- Baris penanda jenis kendaraan dikenali dari pola `NAMA (N Unit)` dan boleh
  memakai huruf A/B/C di kolom No.
- Setiap jenis punya daftar item sendiri. Nama item boleh sama antar jenis.
- Kolom volume di bawah `TERMIN 1`, `TERMIN 2`, dst. adalah qty total untuk
  seluruh unit pada jenis tersebut. Aplikasi membaginya ke setiap plat/unit.
- Volume pada grup `SESUAI PELAKSANAAN` dipakai sebagai qty RAB total.
- `JUMLAH BIAYA` diabaikan karena nilai dihitung dari qty × harga satuan.
- Header dua tingkat (TERMIN di baris atas, VOLUME/HARGA di baris bawah)
  dideteksi otomatis.

### RAB satu jenis / tabel datar

| No | Nama Barang | Satuan | Harga Satuan | Qty Total | Termin 1 | Termin 2 | Termin 3 | Termin 4 |
|----|-------------|--------|--------------|-----------|----------|----------|----------|----------|
| 1  | Service     | unit   | 240000       | 20        | 5        | 5        | 5        | 5        |
| 2  | Oli Mesin   | liter  | 100000       | 20        | 5        | 5        | 5        | 5        |

Ketentuan umum:

- Nama kolom termin dikenali dari pola `Termin 1`, `Term 2`, `Tahap I`,
  `BAP 1`, `Pembayaran 1`, dan sejenisnya. Nama kolom menjadi nama termin.
- Kolom **Qty Total** opsional. Jika tidak ada, total dihitung dari jumlah
  kolom termin.
- Jika hanya ada satu kolom qty dan tidak ada kolom termin, semua qty masuk ke
  satu term (namanya bisa diisi di dialog import).
- Baris subtotal/total/PPN/catatan otomatis dilewati.
- Qty desimal akan memunculkan peringatan dan dibulatkan ke bilangan bulat
  terdekat (0,5 ke atas) setelah kamu menyetujuinya.
- Jika sel berisi formula yang belum punya nilai tersimpan, buka file di Excel
  lalu simpan sekali agar nilainya terbaca.

File contoh: `sample/rab_sample.xlsx` dan `sample/rab_sample_real.xlsx`.

## Format Excel Kendaraan

Kolom yang dicari: `No Kendaraan` / `Plat` / `Nopol` dan `Tipe Kendaraan`.
Contoh ada di `sample/kendaraan_sample.xlsx`. Import plat akan mengisi slot unit
yang sudah dibuat dari RAB. Jenis kendaraan dicocokkan berdasarkan nama; alokasi
qty tidak dihapus. Baris yang tipenya tidak cocok masuk ke jenis default/filter
yang sedang dipilih.

## Aturan Pembagian

Untuk qty `Q` dan `N` kendaraan:

- `dasar = Q // N`
- `sisa R = Q % N`
- `R` kendaraan mendapat tambahan 1, dipilih pengguna.
- Saran awal: kendaraan dengan total penerimaan item tersebut paling sedikit di
  termin-termin sebelumnya.
- Invarian keras: jumlah alokasi semua kendaraan harus sama dengan qty termin.
  Export diblokir jika masih ada selisih.

## Template Invoice

Template default ada di `app/resources/invoice_template.xlsx` dan disalin ke
folder data pengguna saat pertama kali dibutuhkan (misalnya ketika membuka
Pengaturan atau mengekspor invoice). Layout yang dipakai:

- Baris 1–10: header invoice (judul, perusahaan, No PO, tanggal, klien,
  alamat, No Kendaraan, Tipe Kendaraan, header tabel).
- Baris 11 ke bawah: item invoice (`Qty`, `Nama Barang`, `Harga Satuan`,
  `Jumlah`). Jumlah baris menyesuaikan otomatis.
- Setelah item: `Sub Total`, `Disc %`, `TOTAL`.
- Footer: `Hormat Kami,` dan nama perusahaan.

Field yang diisi aplikasi:

| Sel | Isi |
|-----|-----|
| `C1` | Nama perusahaan (Pengaturan) |
| `C2` | Alamat perusahaan (Pengaturan) |
| `B4` | `prefix No PO` + `No Kendaraan` (jika plat kosong memakai label `JENIS #unit`) |
| `B5` | Tanggal invoice termin |
| `D4` | Kepada Yth / nama klien |
| `D5` | Alamat klien |
| `D6` | No Kendaraan (boleh kosong) |
| `D7` | Jenis Kendaraan |

Diskon diisi dalam persen. Nilai `Disc %` ditulis sebagai angka persen, dan
`TOTAL` dihitung dari `Sub Total` dikurangi diskon. Jika ingin mengubah layout,
ganti template lewat **Berkas → Pengaturan**. Syarat minimal: baris 10 kolom A
harus `Qty` dan kolom B harus `Nama Barang`.

## Build EXE

```bat
build_exe.bat
```

Hasil ada di `dist\InvoiceAutomation.exe` (one-file). Template ikut dipaketkan.
Build membutuhkan PyInstaller; script akan memasangnya jika belum ada.

## Lokasi Data

- Database: `%APPDATA%\InvoiceAutomation\data.db`
- Template pengguna: `%APPDATA%\InvoiceAutomation\invoice_template.xlsx`
- Log error: `%APPDATA%\InvoiceAutomation\error.log`

Untuk pengujian, folder data bisa dioverride dengan environment variable
`INVOICE_APP_DATA`.

## Pengujian

```bat
python -m unittest tests.test_core -v
```

Tes mencakup logika pembagian, parsing RAB, validasi database, dan export
invoice (termasuk invoice dengan lebih dari 10 baris item).

## Asumsi & Batasan

Sesuai PRD v0.1 dengan penyesuaian permintaan pengguna:

- Satu pengguna, Windows, offline. Tidak ada sinkronisasi cloud/multi-user.
- Satu proyek dapat berisi **banyak jenis kendaraan**; item dan unit dipisah
  per jenis. Ini memperluas batasan awal PRD yang menyebut satu jenis/proyek.
- Satu termin diekspor menjadi satu invoice **per plat/unit per jenis**.
- Plat boleh dikosongkan; invoice tetap dibuat dengan label `JENIS #unit`.
- Qty desimal dibulatkan setelah konfirmasi; belum ada pembagian pecahan.
- Jika jumlah unit pada suatu jenis berubah, slot unit disesuaikan. Plat lama
  dipertahankan bila memungkinkan; alokasi unit yang dihapus ikut terhapus.
- Output hanya Excel; tidak ada PDF/Word.
- Template invoice menentukan tampilan akhir. Baris item, total, dan footer
  digeser otomatis, tetapi merge/style header mengikuti template.

## Troubleshooting

- **Qty termin tidak terbaca / muncul 0** — periksa baris header dan pemetaan
  kolom di dialog import. Pastikan sel berisi angka, bukan formula tanpa nilai.
- **Tombol export disabled** — termin belum dikunci, masih ada selisih qty,
  atau template tidak ditemukan. Lihat banner merah/kuning di tab terkait.
- **File invoice tertimpa** — centang `Timpa file yang sudah ada`; jika tidak,
  file baru akan diberi akhiran `(2)`, `(3)`, dst.
- **Template rusak** — buka **Berkas → Pengaturan → Reset** untuk memulihkan
  template bawaan.
