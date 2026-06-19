# Project Implementation Plan

## Autonomous Molecular Target Registry for Cancer Drug Discovery

---

### Visi

Membangun sistem otonom yang secara terus-menerus mengumpulkan, memperbarui, memvalidasi, dan menyimpan informasi target molekular kanker dari berbagai sumber ilmiah sehingga menjadi fondasi bagi Knowledge Graph, RAG, dan AI Agent Drug Discovery.

---

# 1. Tujuan

Output akhir:

```text
Cancer Molecular Target Registry (CMTR)

yang berisi:

- Target Molekular
- Protein
- Gen
- Kanker terkait
- Struktur 3D
- Pathway
- Inhibitor
- Biomarker
- Referensi ilmiah
```

Target utama:

> Menghasilkan database target molekular kanker yang terus bertambah secara otomatis dan dapat dipantau kualitasnya secara real-time.

---

# 2. Lingkup

Fokus hanya pada:

## Akuisisi Data

Belum mencakup:

* Knowledge Graph
* RAG
* Agent Reasoning
* Virtual Screening
* Docking
* MD

Hanya membangun:

```text
Internet
 ↓
Crawler
 ↓
Data Collector
 ↓
Entity Resolution & Standardization
 ↓
Registry Database
 ↓
Monitoring Dashboard
```

---

# 3. Sumber Data Prioritas

## Prioritas A (Structured Database)

### UniProt Consortium

Data:

* Gene Symbol
* Protein Name
* Function
* Disease Association

Lisensi: CC BY 4.0 — aman untuk redistribusi dengan atribusi.

---

### Protein Data Bank (PDB)

Data:

* Struktur 3D
* Ligan
* Resolusi

Lisensi: Public domain.

---

### ChEMBL (European Molecular Biology Laboratory)

Data:

* Inhibitor
* Bioactivity
* Drug Target

⚠️ Lisensi campuran — sebagian besar data terbuka, tetapi beberapa kalkulasi properti bersifat komersial dan **tidak boleh diekstrak secara terisolasi untuk melatih model yang mereplikasi proses komersial tersebut**. Perlu ditinjau per jenis data sebelum redistribusi.

---

### Open Targets

Data:

* Disease-target association
* Evidence score

---

## Prioritas B

### National Center for Biotechnology Information (NCBI / PubMed)

Data:

* Artikel ilmiah
* Abstract
* Metadata

⚠️ Full-text article umumnya **tidak** bebas didistribusikan ulang; abstract/metadata relatif aman, tapi tetap cek term of use per publisher di PubMed Central.

---

## Prioritas C

### ClinicalTrials.gov

### The Cancer Genome Atlas Program (TCGA)

---

# 3a. Strategi Akses & Rate Limit per Sumber

Bagian ini wajib selesai **sebelum** connector mana pun mulai dibangun (jadi prasyarat Fase 1, bukan ditemukan saat Fase 2-6 berjalan).

| Sumber | Limit tanpa API key | Limit dengan API key | Strategi yang disarankan |
|---|---|---|---|
| ChEMBL | 1 request/detik | Sedikit lebih tinggi, IP-based jika tanpa key | Untuk volume besar (target-ligand mapping ribuan target), **gunakan local mirror** (dump MySQL ChEMBL) daripada live API; web service hanya untuk update incremental |
| NCBI / PubMed (E-utilities) | 3 request/detik | 10 request/detik | Daftar API key sejak Fase 1; untuk koleksi literature skala besar pertimbangkan NCBI Datasets / FTP bulk daripada E-utilities murni; lebih dari 10 rps butuh izin khusus dari NCBI |
| UniProt | Tidak ada limit ketat terdokumentasi, tapi tetap perlu throttling sopan | — | Gunakan bulk FTP/REST batch endpoint untuk initial load, REST API untuk incremental update |
| PDB (RCSB) | Rate limit standar REST | — | Batch query via search API, hindari one-request-per-structure untuk initial load |
| Open Targets | GraphQL API, ada limit query complexity | — | Gunakan platform API resmi, batasi field per query agar tidak timeout |

**Implikasi desain:** Source Connector Layer harus punya rate limiter + retry/backoff **per sumber** (bukan satu konfigurasi generik untuk semua), plus circuit breaker yang terhubung ke Dashboard 6 (Source Health).

---

# 3b. Tinjauan Lisensi Data (Data Licensing Gate)

Karena CMTR akan jadi fondasi KG/RAG/Agent yang berpotensi dipublikasikan atau dikomersialkan, lisensi setiap sumber harus diverifikasi dan didokumentasikan **sebelum** data disimpan permanen di Registry Database.

Checklist sebelum Fase 2 dimulai:

* [ ] Konfirmasi lisensi UniProt (CC BY 4.0) — siapkan teks atribusi standar
* [ ] Konfirmasi batasan ChEMBL untuk kalkulasi properti komersial
* [ ] Konfirmasi syarat redistribusi abstract/metadata PubMed vs full-text
* [ ] Konfirmasi lisensi Open Targets (biasanya CC0, tetap verifikasi versi terbaru)
* [ ] Dokumentasikan semua hasil di `LICENSES.md` dalam repo, per-sumber

---

# 4. Arsitektur Sistem

```text
Scheduler
    │
    ▼

Source Connector Layer (dengan rate limiter & retry per sumber)
    │
    ├── UniProt Connector
    ├── PDB Connector
    ├── ChEMBL Connector
    ├── OpenTargets Connector
    └── PubMed Connector

    ▼

Data Standardization Layer

    ▼

Entity Resolution Layer (cross-reference ID antar sumber)

    ▼

Validation Layer

    ▼

Registry Database

    ▼

Monitoring Dashboard
```

## Catatan Entity Resolution

Satu target molekular sering punya ID berbeda di tiap sumber (UniProt accession ≠ ChEMBL target ID ≠ PDB chain ID). Tanpa layer resolusi entitas yang eksplisit, risiko duplikasi/data terpecah jadi tinggi — ini berdampak langsung ke KPI "Duplicate Rate" di Dashboard 5. Layer ini bertugas:

* Memetakan ID antar sumber (mis. via UniProt cross-reference table sebagai anchor)
* Menentukan source of truth saat ada konflik nilai field yang sama
* Menyimpan riwayat mapping untuk audit

---

# 5. Model Data Inti(Diperkaya)

Field tambahan dibanding draf awal: provenance per field, timestamp, confidence/validation status.

```json
{
  "target_id": "",
  "gene_symbol": "",
  "protein_name": "",
  "uniprot_id": "",
  "organism": "",
  "target_class": "",
  "associated_cancers": [],
  "pathways": [],
  "pdb_ids": [],
  "known_inhibitors": [],
  "evidence_score": "",
  "references": [],

  "source_provenance": {
    "gene_symbol": "uniprot",
    "known_inhibitors": "chembl",
    "associated_cancers": "opentargets"
  },
  "confidence_score": "",
  "validation_status": "pending | validated | conflicted",
  "created_at": "",
  "updated_at": "",
  "last_synced_at": {
    "uniprot": "",
    "pdb": "",
    "chembl": "",
    "opentargets": "",
    "pubmed": ""
  }
}
```

### Catatan implementasi skema (PostgreSQL)

Struktur di atas berbentuk dokumen (array nested), tapi Fase 1 menetapkan PostgreSQL sebagai database utama. Dua opsi:

1. **Relasional penuh** — pecah `pdb_ids`, `known_inhibitors`, `references`, `pathways` jadi tabel anak masing-masing dengan foreign key ke `target_id`. Lebih query-friendly untuk dashboard dan KG nantinya.
2. **Hybrid JSONB** — simpan field skalar di kolom biasa, array kompleks di kolom `JSONB` dengan index GIN. Lebih cepat dibangun di awal, tapi migrasi ke relasional penuh nanti lebih mahal.

Rekomendasi: mulai dengan opsi relasional penuh untuk `pdb_ids`, `known_inhibitors`, `references` (karena ini yang paling sering di-query terpisah), dan JSONB hanya untuk `source_provenance`/`last_synced_at` (metadata, jarang di-query langsung).

---

# 6. Fase Implementasi

## Fase 0 (sebelum Bulan 1)

### Rate Limit & Licensing Gate

Deliverables:

* Dokumen strategi akses & rate limit per sumber (lihat §3a)
* `LICENSES.md` terisi lengkap (lihat §3b)
* API key terdaftar untuk NCBI dan ChEMBL (jika tersedia)

Target:

```text
Tidak ada connector dibangun sebelum gate ini selesai
```

---

## Fase 1 (Bulan 1)

### Infrastructure Setup

Deliverables:

* Server
* PostgreSQL (dengan skema relasional dasar dari §5)
* Object Storage
* Scheduler
* Rate limiter & circuit breaker generik (dikonfigurasi per sumber)

Target:

```text
System online
```

---

## Fase 2 (Bulan 2)

### UniProt Collector

Target:

```text
100% protein manusia terkait kanker
```

Deliverables:

* API Connector (bulk FTP untuk initial load, REST untuk incremental)
* Incremental Update

---

## Fase 3 (Bulan 3)

### PDB Collector

Target:

```text
Seluruh struktur target kanker
```

Deliverables:

* PDB Metadata
* Cross-reference UniProt (lewat Entity Resolution Layer)

---

## Fase 4 (Bulan 4)

### ChEMBL Collector

Target:

```text
Target-ligand mapping
```

Deliverables:

* Bioactivity
* Inhibitor list
* Local mirror ChEMBL (jika volume besar) atau pipeline incremental via API dengan rate limiter aktif

---

## Fase 5 (Bulan 5)

### Open Targets Collector

Target:

```text
Disease-target association
```

---

## Fase 6 (Bulan 6)

### PubMed Collector

Target:

```text
Target-related literature
```

Deliverables:

* API key NCBI terpasang
* Pipeline metadata/abstract (bukan full-text, sesuai gate lisensi §3b)

---

### Catatan paralelisasi

Connector Fase 2–6 secara teknis sebagian besar independen satu sama lain (ketergantungan hanya pada Entity Resolution Layer untuk cross-reference, bukan pada urutan pembangunan). Jika ada lebih dari satu orang di tim, Fase 2–5 bisa dikerjakan paralel setelah Fase 1 selesai, memotong timeline dari 6 bulan menjadi sekitar 3–4 bulan. Urutan sekuensial di atas diasumsikan untuk pengerjaan solo/kapasitas terbatas.

---

# 7. Sistem Monitoring Keberhasilan

Ini harus dibangun sejak awal.

---

## Dashboard 1

### Data Growth

KPI:

```text
Total Target
Total Protein
Total Cancer
Total PDB
Total Inhibitor
Total Reference
```

---

## Dashboard 2

### Coverage

KPI:

```text
Coverage UniProt
Coverage PDB
Coverage ChEMBL
Coverage OpenTargets
Coverage PubMed
```

Formula:

```text
Coverage Score
=
Target Terisi
/
Target Diharapkan
```

### Definisi baseline "Target Diharapkan"

Sebelum dashboard ini dibangun, denominator harus dipatok ke angka konkret, misalnya:

* **Baseline awal**: jumlah gene-disease association kanker dari Open Targets dengan evidence score di atas threshold tertentu (misal ≥ 0.5), atau
* **Baseline konservatif**: jumlah gen di COSMIC Cancer Gene Census (~700-an gen well-characterized) sebagai lower bound, dengan Open Targets sebagai upper bound

Tanpa baseline ini, "Coverage 70%" tidak punya makna yang bisa diverifikasi.

---

## Dashboard 3

### Completeness

Per target:

| Field        | Bobot |
| ------------ | ----- |
| Gene Symbol  | 10    |
| UniProt      | 10    |
| Protein Name | 10    |
| PDB          | 20    |
| Pathway      | 20    |
| Disease      | 15    |
| Inhibitor    | 15    |

Formula:

```text
Completeness =
Field Terisi / Total Field
```

---

## Dashboard 4

### Freshness

KPI:

```text
Last Update

Data Baru Hari Ini

Data Baru Minggu Ini

Average Sync Time
```

Target:

```text
< 24 jam
```

---

## Dashboard 5

### Data Quality

KPI:

```text
Duplicate Rate

Missing Field Rate

Broken Reference Rate

Validation Failure Rate
```

Target:

```text
Duplicate < 5%
```

*Duplicate Rate di dashboard ini bergantung langsung pada kualitas Entity Resolution Layer (§4) — kalau layer itu lemah, angka ini akan tinggi terus-menerus.*

---

## Dashboard 6

### Source Health

Memantau:

```text
UniProt API
PDB API
ChEMBL API
OpenTargets API
PubMed API
```

Status:

```text
ONLINE
DEGRADED
OFFLINE
```

*Tambahkan metrik rate-limit-hit-rate per sumber di sini, terhubung ke circuit breaker dari §3a.*

---

# 8. Indikator Keberhasilan

## Minimal Viable Success

```text
Target Unik > 5.000

Cancer Types > 100

PDB > 10.000

References > 100.000

Coverage > 70%

Completeness > 70%

Freshness < 7 hari

Duplicate < 10%
```

---

## Target Success

```text
Target Unik > 15.000

Cancer Types > 200

PDB > 25.000

References > 500.000

Coverage > 85%

Completeness > 80%

Freshness < 24 jam

Duplicate < 5%
```

### Catatan sanity check

Angka "Target Unik > 15.000" cukup ambisius dibanding referensi seperti COSMIC Cancer Gene Census (~700-an gen well-characterized). Angka ini baru realistis kalau definisi "target" diperluas mencakup seluruh gene-disease association dari Open Targets untuk semua jenis kanker dengan threshold evidence score rendah. **Tentukan threshold evidence score yang dipakai sebelum angka ini difinalkan**, supaya target di atas bisa diverifikasi terhadap data riil, bukan angka aspirasional.

---

# 9. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Rate limit ChEMBL/PubMed memperlambat initial load | Fase 4/6 mundur dari jadwal | Local mirror ChEMBL, API key NCBI, bulk FTP untuk initial load |
| Entity resolution lemah → duplikasi tinggi | Dashboard 5 KPI gagal terus | Bangun Entity Resolution Layer sebagai komponen eksplisit, bukan side-effect Standardization Layer |
| Lisensi data tidak jelas saat mau dipublikasi/dikomersialkan | Risiko hukum di akhir proyek | Gate lisensi di Fase 0, dokumentasi `LICENSES.md` |
| Target Unik 15.000 tidak realistis | KPI Target Success tidak pernah tercapai, demotivasi | Definisikan threshold evidence score & baseline sebelum finalisasi angka |
| Solo developer, 5 connector sekuensial | Timeline 6 bulan molor jika ada hambatan di satu connector | Evaluasi kemungkinan paralelisasi (lihat §6) jika ada tambahan kapasitas |

---

# 10. Deliverable Akhir

Pada akhir proyek, Anda harus memiliki:

```text
Cancer Molecular Target Registry

✓ otomatis berjalan

✓ otomatis update

✓ otomatis validasi

✓ dashboard monitoring

✓ API pencarian target

✓ dokumentasi lisensi data per sumber

✓ siap menjadi sumber Knowledge Graph

✓ siap menjadi sumber RAG

✓ siap menjadi fondasi AI Agent Drug Discovery
```