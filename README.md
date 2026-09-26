# StockSense — Inventory Management System

An Odoo 17 Community module providing centralized inventory management with an
auditable movement ledger. Built for the Odoo Hackathon.

## Features

- **Product & Category Management** — Hierarchical product classification with SKU, UoM, barcode
- **Multi-Warehouse Support** — Multiple warehouses with auto-generated locations
- **Hierarchical Locations** — Nested location tree within warehouses
- **Inventory Operations** — Receipts, Deliveries, Internal Transfers, Adjustments
- **Auditable Movement Ledger** — Append-only, tamper-proof stock movement history
- **Hybrid Stock Balance** — Cached current stock + movement-based audit trail
- **Reorder Rules** — Low-stock detection with configurable thresholds
- **Security Groups** — User and Manager roles with appropriate access control

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the complete design rationale.

**Three-Layer Design:**
1. **Operation** (business document) — what the user intends
2. **Movement** (ledger entry) — what actually happened to stock
3. **Balance** (cached state) — current stock levels for fast queries

## Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Odoo 17 Community Edition

## Installation

### 1. Set Up Odoo 17

```bash
# Clone Odoo 17 (if not already done)
git clone --depth 1 --branch 17.0 https://github.com/odoo/odoo.git /path/to/odoo17

# Install dependencies
cd /path/to/odoo17
pip install -r requirements.txt
pip install lxml_html_clean pywin32  # Windows-specific
```

### 2. Configure Odoo

Create or edit `odoo.conf`:

```ini
[options]
db_host = localhost
db_port = 5432
db_user = odoo
db_password = odoo
db_name = stocksense_db
addons_path = /path/to/odoo17/addons,/path/to/StockSense
```

### 3. Create the Database

```bash
createdb -U odoo stocksense_db
```

### 4. Install the Module

```bash
# Start Odoo with module installation
python /path/to/odoo17/odoo-bin -c odoo.conf -i stocksense
```

Or install via the Odoo web interface:
1. Go to **Apps** menu
2. Click **Update Apps List**
3. Search for **StockSense**
4. Click **Install**

## Running

```bash
python /path/to/odoo17/odoo-bin -c odoo.conf
```

Then open `http://localhost:8069` in your browser.

## Running Tests

```bash
python /path/to/odoo17/odoo-bin -c odoo.conf -d stocksense_test --test-enable --test-tags stocksense -i stocksense --stop-after-init
```

## Module Structure

```
stocksense/
├── __init__.py              # Module root
├── __manifest__.py          # Odoo module manifest
├── models/
│   ├── __init__.py
│   ├── category.py          # Product categories (hierarchical)
│   ├── product.py           # Product master data
│   ├── warehouse.py         # Warehouses with auto-location creation
│   ├── location.py          # Hierarchical stock locations
│   ├── operation.py         # Business operations (receipt/delivery/transfer/adjustment)
│   ├── movement.py          # Immutable movement ledger
│   ├── stock.py             # Cached stock balances
│   └── reorder_rule.py      # Low-stock alert rules
├── security/
│   ├── security_groups.xml  # User and Manager groups
│   └── ir.model.access.csv  # Model access control list
├── views/
│   ├── category_views.xml
│   ├── product_views.xml
│   ├── warehouse_views.xml
│   ├── location_views.xml
│   ├── operation_views.xml
│   ├── movement_views.xml
│   ├── stock_views.xml
│   ├── reorder_rule_views.xml
│   └── menu.xml             # Application menu structure
├── data/
│   ├── sequence_data.xml    # Auto-incrementing operation references
│   └── location_data.xml    # Virtual locations (Supplier/Customer/Adjustment)
├── tests/
│   ├── __init__.py
│   └── test_inventory.py    # Comprehensive inventory invariant tests
├── ARCHITECTURE.md           # Design rationale and entity relationships
└── README.md                 # This file
```

## License

LGPL-3
