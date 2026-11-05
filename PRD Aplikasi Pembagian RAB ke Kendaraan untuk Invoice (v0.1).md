# PRD: Aplikasi Pembagian RAB ke Kendaraan untuk Invoice (v0.1)

## 1. Tujuan

Mengotomatiskan pembagian qty item RAB ke setiap kendaraan per termin, lalu menghasilkan Excel invoice, sehingga tidak perlu dihitung manual dan risiko salah bagi berkurang.

**Pengguna:** satu orang (pemilik), Windows, offline.

**Indikator sukses:** invoice satu termin selesai dalam hitungan menit, total qty per item sama persis dengan qty termin di RAB, dan tidak ada selisih antar termin.

## 2. Ruang Lingkup

**Masuk (v1):**

- Import Excel RAB dengan format tetap, termasuk qty per termin
- Import atau input list kendaraan (satu jenis per proyek)
- Pembagian otomatis per item, per termin
- Konfirmasi user bila qty tidak habis dibagi
- Pelacakan alokasi antar termin
- Export Excel invoice per termin

**Tidak masuk (v1):** multi-user, online/cloud, campuran jenis kendaraan, input kode barang ala POS, pembuatan PDF/Word.

## 3. Alur Utama

1. Buat proyek, lalu import Excel RAB (termin ikut terbaca) dan list kendaraan.
2. Validasi: total qty semua termin harus sama dengan qty RAB per item. Jika tidak, tampilkan daftar item yang bermasalah.
3. Pilih termin, lalu klik **Bagi**.
4. Item yang habis dibagi langsung teralokasi. Item yang tidak habis dibagi masuk antrean konfirmasi.
5. Review hasil dalam tabel (item × nomor kendaraan), lalu kunci alokasi termin tersebut.
6. Export Excel sesuai template output.

## 4. Aturan Pembagian

- Untuk qty Q dan N kendaraan: jika Q habis dibagi N, setiap kendaraan mendapat Q/N.
- Jika tidak habis dibagi, dasar per kendaraan = lantai(Q/N), dan sisa R = Q − dasar×N. Sebanyak R kendaraan mendapat +1, dan **user memilih kendaraan mana** (tidak ditentukan otomatis). Contoh: Q=4, N=5 berarti dasar 0, R=4, sehingga user memilih 4 kendaraan yang mendapat 1.
- Aplikasi menyarankan default, yaitu kendaraan yang paling sedikit menerima item tersebut di termin sebelumnya, tetapi user bisa menimpanya.
- Qty selalu bilangan bulat. Qty desimal (misal jasa atau liter) perlu dikonfirmasi, lihat Pertanyaan Terbuka.
- Invarian wajib: jumlah alokasi semua kendaraan = qty termin. Jika tidak, export diblokir.

## 5. Kebutuhan Fungsional

| ID | Kebutuhan | Prioritas |
| --- | --- | --- |
| F1 | Import RAB Excel (format tetap) dan baca kolom termin | Wajib |
| F2 | Import/input list kendaraan | Wajib |
| F3 | Validasi total termin = qty RAB | Wajib |
| F4 | Pembagian otomatis item yang habis dibagi | Wajib |
| F5 | Dialog konfirmasi untuk item tidak habis dibagi | Wajib |
| F6 | Simpan status proyek lokal (alokasi per termin, kunci termin) | Wajib |
| F7 | Pelacakan sisa volume yang belum ditagihkan | Wajib |
| F8 | Export Excel sesuai template | Wajib (menunggu desain) |
| F9 | Edit manual alokasi sebelum dikunci, dengan validasi invarian | Sebaiknya ada |
| F10 | Log perubahan alokasi | Opsional |

## 6. Kebutuhan Non-Fungsional

- Berjalan offline penuh, installer atau file .exe tunggal
- Data tersimpan lokal (disarankan SQLite) dan bisa dibuka kembali
- Perhitungan harus deterministik dan bisa diaudit
- Pesan error menyebut item/baris Excel yang bermasalah

## 7. Rekomendasi Teknis

Python + PySide6 (UI) + openpyxl (baca/tulis Excel) + SQLite, dikemas dengan PyInstaller menjadi .exe. Alasannya cepat dibuat, library Excel matang, dan sesuai latar belakang data pengguna. Jika nanti perlu tampilan lebih ringan, bisa diganti, tetapi logika pembagian tetap terpisah dari UI.

## 8. Risiko

- Format RAB "pasti" tetapi bisa bergeser sedikit (merge cell, baris subtotal), sehingga parser perlu dibuat tegas dan memberi error jelas.
- Pembagian sisa yang tidak dilacak antar termin bisa membuat satu kendaraan terus menerima jatah lebih. Ini ditangani lewat saran default di bagian 4.
- Template output belum ada, jadi F8 belum bisa dikunci.

## 9. Asumsi

- Satu proyek memiliki satu RAB dan satu list kendaraan tetap.
- Harga satuan diambil dari RAB, bukan dihitung ulang.
- Jumlah kendaraan tidak berubah antar termin.

## 10. Pertanyaan Terbuka

1. Apakah ada item bersatuan non-bulat (liter, m², paket/ls)? Bagaimana pembagiannya?
2. Bisakah list kendaraan berubah di tengah proyek (kendaraan ditambah/dihapus antar termin)?
3. Apakah invoice perlu menampilkan rincian per kendaraan, ringkasan per item, atau keduanya?
4. Satu invoice mencakup satu termin saja, atau bisa gabungan beberapa termin?

## 11. Langkah Berikutnya

Kirim contoh Excel RAB (boleh data dummy) untuk merinci spesifikasi parser, lalu desain template output.
