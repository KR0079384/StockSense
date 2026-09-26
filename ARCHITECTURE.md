# StockSense — Architecture Document

## 1. Overview

StockSense is a centralized inventory management system built as an Odoo 17 Community custom module. It provides full traceability of stock movements across warehouses and locations through an **auditable movement ledger**.

The system covers: Products, Categories, Warehouses, Locations, Receipts, Deliveries, Internal Transfers, Multi-Line Stock Adjustments, Reorder Rules, and a Stock Ledger.

---

## 2. Core Design Principle: Movement Ledger

Every stock-changing operation produces one or more **inventory movement** records. The movement ledger is the single source of truth for answering:

> *"Why is the current stock at this location what it is?"*

Movements are **append-only**. Historical records are never deleted or mutated (only cancelled via reversing entries if needed). This guarantees full auditability and historical reconstruction.

---

## 3. Entity Relationship Design

### 3.1 Entity Summary

| Entity | Odoo Model | Purpose |
|--------|-----------|---------|
| Product Category | `stocksense.category` | Hierarchical product classification |
| Product | `stocksense.product` | Master product data (SKU, UoM, reorder rules) |
| Warehouse | `stocksense.warehouse` | Physical warehouse with auto-generated locations |
| Location | `stocksense.location` | Hierarchical stock-holding location |
| Inventory Operation | `stocksense.operation` | Business document (receipt, delivery, transfer, adjustment) |
| Operation Line | `stocksense.operation.line` | Multi-product detail line for an operation |
| Inventory Movement | `stocksense.movement` | Individual stock movement event (ledger entry) |
| Stock Balance | `stocksense.stock` | Cached current stock per product per location |
| Reorder Rule | `stocksense.reorder.rule` | Low-stock threshold and reorder parameters |

### 3.2 Entity Relationship Diagram

```
                  ┌─────────────────┐       ┌─────────────────┐
                  │  Category       │◄──────│  Product        │
                  │  (hierarchical) │  M:1  │  (SKU, UoM,     │
                  └─────────────────┘       │   reorder info) │
                                            └────────┬────────┘
                                                     │
                                      ┌──────────────┼──────────────┐
                                      │              │              │
                                      ▼              ▼              ▼
                             ┌──────────────┐ ┌──────────┐ ┌──────────────┐
                             │  Operation   │ │  Stock   │ │ Reorder Rule │
                             │   Line       │ │  Balance │ │ (threshold,  │
                             │(multi-product│ │  (cache) │ │  reorder qty)│
                             └──────┬───────┘ └──────────┘ └──────────────┘
                                    │
                             ┌──────┴───────┐
                             │  Movement    │
                             │  (ledger     │
                             │   entry)     │
                             └──────┬───────┘
                                    │ M:1
                                    ▼
                             ┌──────────────┐
                             │  Operation   │
                             │  (business   │
                             │   document)  │
                             └──────────────┘

┌─────────────────┐       ┌─────────────────┐
│  Warehouse      │──────►│  Location       │
│                 │  1:M  │  (hierarchical) │
└─────────────────┘       └─────────────────┘

Location is referenced by: Movement (source/dest), Stock (location), Reorder Rule (location)
```

---

## 4. Three-Layer Separation & Multi-Product Flow

This is the core architectural foundation:

### Layer 1: Business Operation & Lines (Document & Details)
**Models: `stocksense.operation` & `stocksense.operation.line`**

Represents a business intent containing one or more products:
- `stocksense.operation`: Master document with operation type (`receipt`, `delivery`, `internal`, `adjustment`), explicit adjustment direction (`gain`, `loss`), locations, scheduled date, and status (`draft → confirmed → done`).
- `stocksense.operation.line`: Detail lines representing specific product and quantity pairs.

### Layer 2: Inventory Movement (Ledger Entry)
**Model: `stocksense.movement`**

Represents the actual stock change event. Created when an operation is validated:
- Immutable once created (append-only ledger).
- Links to both `operation_id` and specific `operation_line_id`.
- Records: product, source location, destination location, quantity, timestamp, user, reason.

### Layer 3: Stock Balance (Current State Cache)
**Model: `stocksense.stock`**

Represents the current quantity of a product at a specific location:
- Updated atomically whenever a movement is created.
- Can be reconstructed from movements at any time.

---

## 5. Explicit Adjustment Direction Design

Inventory adjustments use explicit, non-ambiguous directions:
- `gain` (Stock Gain): Stock flows from Virtual `Inventory Adjustment` location to internal destination location.
- `loss` (Stock Loss): Stock flows from internal source location to Virtual `Inventory Adjustment` location.

Validation requires specifying `adjustment_type` (`gain` or `loss`) for all adjustment operations.

---

## 6. Testing & Environment Verification

- **PostgreSQL 18** database instance configured and active.
- **Odoo 17 Community** framework loaded with `StockSense` custom module.
- **Test Suite Execution**: 18 unit tests executed via Odoo's test runner (`odoo-bin --test-tags /StockSense`).
- **Test Results**: 18 passed, 0 failed, 0 errors.

---

## 7. Database Setup Requirements

To run StockSense locally with Odoo 17 and PostgreSQL:

1. **PostgreSQL**: PostgreSQL 18+ listening on port 5433 (or standard 5432) with a UTF8 encoded database:
   ```bash
   createdb -h localhost -p 5433 -U odoo -T template0 --encoding=UTF8 stocksense_db
   ```
2. **Odoo Configuration (`odoo.conf`)**:
   ```ini
   [options]
   db_host = 127.0.0.1
   db_port = 5433
   db_user = odoo
   db_password = 
   db_name = stocksense_db
   addons_path = k:\Projects\odoo17\addons,k:\Projects
   ```
3. **Execute Test Suite**:
   ```bash
   python k:\Projects\odoo17\odoo-bin -c k:\Projects\StockSense\odoo.conf -d stocksense_db -i StockSense --test-tags /StockSense --stop-after-init
   ```
