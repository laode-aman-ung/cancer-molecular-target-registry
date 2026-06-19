# Cancer Molecular Target Registry (CMTR)

Sistem otonom untuk mengumpulkan, memperbarui, memvalidasi, dan menyimpan data **target molekular kanker** dari berbagai sumber ilmiah terbuka. Fondasi untuk Knowledge Graph, RAG, dan AI Agent Drug Discovery.

## Arsitektur

```
Sumber Data (UniProt, PDB, ChEMBL, OpenTargets, PubMed)
    ↓
Source Connector Layer  (rate limiter + retry per sumber)
    ↓
Data Standardization & Entity Resolution
    ↓
Registry Database (SQLite → PostgreSQL)
    ↓
Monitoring Dashboard (CLI)
```

## Sumber Data

| Sumber | Data | Status |
|--------|------|--------|
| UniProt | Protein, gen, fungsi, disease association | ✅ |
| RCSB PDB | Struktur 3D, resolusi, metode | ✅ |
| ChEMBL | Inhibitor, bioactivity (IC50/Ki/Kd) | ✅ |
| Open Targets | Disease-target association score | 🔜 |
| PubMed | Referensi ilmiah, abstract | 🔜 |

## Instalasi

```bash
git clone https://github.com/<username>/cmtr.git
cd cmtr
pip install -r requirements.txt
cp .env.example .env
# Edit .env jika perlu (opsional untuk prototype)
```

## Penggunaan

### Jalankan pipeline

```bash
# Full pipeline semua sumber
python run.py pipeline all

# Per connector
python run.py pipeline uniprot
python run.py pipeline pdb
python run.py pipeline chembl

# Mode incremental (hanya data baru sejak sync terakhir)
python run.py pipeline uniprot --incremental
```

### Lihat dashboard monitoring

```bash
python run.py dashboard
```

### Jalankan scheduler otomatis

```bash
python scheduler.py
# Daily incremental: 02:00 UTC
# Weekly full sync: Minggu 03:00 UTC
```

## Model Data

Setiap target molekular menyimpan:

```json
{
  "target_id": "CMTR-P00519",
  "gene_symbol": "ABL1",
  "protein_name": "Tyrosine-protein kinase ABL1",
  "uniprot_id": "P00519",
  "associated_cancers": ["Leukemia, chronic myeloid", ...],
  "pathways": ["Cell cycle", "Apoptosis", ...],
  "pdb_structures": [{"pdb_id": "1IEP", "resolution": 2.1, "method": "X-RAY DIFFRACTION"}],
  "inhibitors": [{"chembl_id": "CHEMBL1", "compound_name": "Imatinib", "IC50": 600, "unit": "nM"}],
  "source_provenance": {"gene_symbol": "uniprot", "inhibitors": "chembl"},
  "validation_status": "pending | validated | conflicted"
}
```

## Monitoring KPI

| Dashboard | KPI |
|-----------|-----|
| Data Growth | Total targets, cancer types, PDB, inhibitors, references |
| Coverage | % targets tersync per sumber |
| Completeness | % field terisi per target (berbobot) |
| Freshness | Waktu sync terakhir per sumber |
| Data Quality | Duplicate rate, missing field rate |
| Source Health | Status API per sumber (OK / RUNNING / ERROR) |

## Struktur Proyek

```
cmtr/
├── connectors/      # Source connectors (UniProt, PDB, ChEMBL, ...)
├── db/              # Schema SQLite & helper koneksi
├── monitoring/      # CLI dashboard (Rich)
└── utils/           # Rate limiter per sumber
run.py               # Entry point utama
scheduler.py         # APScheduler untuk sync otomatis
requirements.txt
.env.example
```

## Lisensi Data Sumber

| Sumber | Lisensi |
|--------|---------|
| UniProt | CC BY 4.0 |
| RCSB PDB | Public Domain |
| ChEMBL | CC BY-SA 3.0 — perhatikan batasan kalkulasi komersial |
| Open Targets | Apache 2.0 |
| PubMed | Abstract/metadata aman; full-text per publisher |

## Roadmap

- [x] UniProt connector
- [x] PDB connector  
- [x] ChEMBL connector
- [ ] Open Targets connector
- [ ] PubMed connector
- [ ] Entity Resolution Layer
- [ ] PostgreSQL migration
- [ ] REST API pencarian target
- [ ] Knowledge Graph export
