# StockSense — Architecture Document

## 1. Overview

StockSense is a centralized inventory management system built as an Odoo 17 Community custom module. It provides full traceability of stock movements across warehouses and locations through an **auditable movement ledger**.

The system covers: Products, Categories, Warehouses, Locations, Receipts, Deliveries, Internal Transfers, Stock Adjustments, Reorder Rules, and a Stock Ledger.

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
                             │  Movement    │ │  Stock   │ │ Reorder Rule │
                             │  (ledger     │ │  Balance │ │ (threshold,  │
                             │   entry)     │ │  (cache) │ │  reorder qty)│
                             └──────┬───────┘ └──────────┘ └──────────────┘
                                    │
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

## 4. Three-Layer Separation

This is the most important architectural distinction:

### Layer 1: Business Operation (Document)
**Model: `stocksense.operation`**

Represents a business intent: "We want to receive 100 units from Vendor X" or "Transfer 60 units from Warehouse A to B".

- Has a lifecycle: `draft → confirmed → done` (or `cancelled`)
- References products, quantities, source/destination
- Is the user-facing document

### Layer 2: Inventory Movement (Ledger Entry)
**Model: `stocksense.movement`**

Represents the actual stock change event. Created when an operation is validated/completed.

- Immutable once created (append-only ledger)
- Records: product, source location, destination location, quantity, timestamp, user, operation reference
- One operation may create multiple movements

### Layer 3: Stock Balance (Current State Cache)
**Model: `stocksense.stock`**

Represents the current quantity of a product at a specific location.

- Updated whenever a movement is created
- Can be reconstructed from movements at any time
- Exists for query performance (avoids summing all movements for every stock check)

### Why Three Layers?

| Concern | Operation | Movement | Balance |
|---------|-----------|----------|---------|
| User workflow | ✓ | | |
| Audit trail | | ✓ | |
| Current stock query | | | ✓ |
| Historical reconstruction | | ✓ | |
| Business rules / validation | ✓ | | |
| Dashboard KPIs | | ✓ | ✓ |

---

## 5. Stock Balance Strategy: Hybrid Approach

### Decision: Cached balance + movement-based audit

**Why not pure computed (sum all movements)?**
- Querying current stock would require aggregating the entire movement history
- Becomes progressively slower as history grows
- Not practical for dashboards, reorder checks, or search/filtering

**Why not pure stored balance (no movements)?**
- No audit trail
- Cannot answer "how did stock get to this level?"
- Cannot reconstruct historical stock at a point in time
- No traceability for adjustments or corrections

**Chosen: Hybrid**
- `stocksense.stock` stores the current balance per (product, location) pair
- Updated atomically when movements are created
- `stocksense.movement` stores every change as an append-only ledger
- Balance can be verified/reconciled against movement sum at any time
- Historical stock at any point = sum of all movements up to that timestamp

### Consistency Guarantee

The balance update and movement creation happen within the same ORM transaction. Odoo's ORM ensures that both succeed or both fail — maintaining consistency between the ledger and the cached balance.

---

## 6. Movement Model Details

### Movement Types

| Type | Source | Destination | Example |
|------|--------|-------------|---------|
| `receipt` | Virtual/Supplier | Physical Location | Vendor delivers 100 units |
| `delivery` | Physical Location | Virtual/Customer | Ship 20 units to customer |
| `internal` | Physical Location | Physical Location | Move stock between locations |
| `adjustment_in` | Virtual/Adjustment | Physical Location | Found extra stock during count |
| `adjustment_out` | Physical Location | Virtual/Adjustment | Stock loss/damage/shrinkage |

### Virtual Locations

Following Odoo's established convention, we use "virtual" locations for external sources/sinks:

- **Supplier Location**: Source for incoming goods (receipts)
- **Customer Location**: Destination for outgoing goods (deliveries)
- **Adjustment Location**: Source/destination for inventory adjustments

These are system-generated, non-physical locations that exist to maintain the double-entry nature of the ledger. Every movement always has both a source and a destination.

### Movement Example: Internal Transfer

Operation: "Transfer 60 units of Widget-A from Main Warehouse → Production Rack"

Movement record created:
```
product: Widget-A
source_location: Main Warehouse/Stock
destination_location: Production Rack
quantity: 60
operation_type: internal
operation_ref: INT/2024/0001
timestamp: 2024-01-15 10:30:00
user: admin
status: done
```

Balance updates:
- Main Warehouse/Stock: Widget-A qty -= 60
- Production Rack: Widget-A qty += 60
- Total company stock: unchanged ✓

---

## 7. Location Hierarchy

Locations follow a parent-child tree structure:

```
Warehouse: Main Warehouse
├── Stock (default internal location)
├── Input (receiving area)
├── Output (shipping area)
├── Quality Control
└── Production
    ├── Assembly Line 1
    └── Assembly Line 2

Virtual Locations (system-wide, no warehouse):
├── Suppliers
├── Customers
└── Inventory Adjustments
```

Each warehouse auto-creates a default "Stock" location. Users can add sub-locations as needed.

Location types:
- `internal`: Physical location within a warehouse (holds stock)
- `supplier`: Virtual location for vendors/suppliers
- `customer`: Virtual location for customers
- `adjustment`: Virtual location for inventory adjustments
- `transit`: Location for goods in transit between warehouses

---

## 8. Reorder Rules

Each reorder rule is defined per (product, location) pair:

- **Minimum Quantity**: When stock falls below this, trigger reorder alert
- **Maximum Quantity**: Suggested reorder-up-to level
- **Reorder Quantity**: Default order quantity

The reorder check is implemented as a computed field on the stock balance model, making it efficient for dashboard queries.

---

## 9. Data Integrity Constraints

### Model-Level Constraints (Python)
1. Movement quantity must be positive
2. Operation cannot transfer to the same location as source
3. Product SKU must be unique
4. Stock balance quantity cannot go negative (configurable)
5. Operation state transitions are enforced (no skipping states)

### SQL-Level Constraints
1. Unique constraint on stock balance: `(product_id, location_id)`
2. Unique constraint on product SKU
3. Required fields enforced via `required=True`

### Business Rule Constraints
1. Only `done` operations produce movements
2. Movements cannot be manually created (only via operation validation)
3. Cancelled operations cannot be re-confirmed
4. Stock quantity is checked before delivery/transfer operations

---

## 10. Security Model

### Groups
- **StockSense User**: Can view products, stock, operations; can create/confirm operations
- **StockSense Manager**: Full CRUD on all models; can cancel operations; can modify reorder rules

### Record Rules
- All users can read products and stock balances
- Only managers can delete/archive products
- Movement records are read-only for all users (immutable ledger)
- Operations follow state-based access (draft editable, done read-only)

---

## 11. Module Structure

```
stocksense/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── category.py
│   ├── product.py
│   ├── warehouse.py
│   ├── location.py
│   ├── operation.py
│   ├── movement.py
│   ├── stock.py
│   └── reorder_rule.py
├── security/
│   ├── security_groups.xml
│   └── ir.model.access.csv
├── views/
│   ├── category_views.xml
│   ├── product_views.xml
│   ├── warehouse_views.xml
│   ├── location_views.xml
│   ├── operation_views.xml
│   ├── movement_views.xml
│   ├── stock_views.xml
│   └── menu.xml
├── data/
│   ├── location_data.xml
│   └── sequence_data.xml
├── tests/
│   ├── __init__.py
│   └── test_inventory.py
└── README.md
```

---

## 12. Future Dashboard Queries (Phase 2 Readiness)

The hybrid balance + movement architecture enables efficient queries for:

| KPI | Query Source |
|-----|-------------|
| Current stock by product | `stocksense.stock` — direct read |
| Current stock by location | `stocksense.stock` — filtered read |
| Low stock alerts | `stocksense.stock` JOIN `stocksense.reorder.rule` |
| Stock movement history | `stocksense.movement` — filtered/sorted |
| Stock value over time | `stocksense.movement` — aggregation by date |
| Top moving products | `stocksense.movement` — group by product, count |
| Warehouse utilization | `stocksense.stock` — group by warehouse |
| Receipt/delivery volume | `stocksense.operation` — filtered by type + date |

All these queries hit indexed, purpose-built tables rather than requiring expensive ledger aggregations.

---

## 13. Why This Design Is Appropriate for StockSense

1. **Traceability**: Every stock change is recorded with who, what, when, where, and why
2. **Auditability**: Append-only movement ledger prevents history tampering
3. **Correctness**: Hybrid balance ensures cached stock matches movement history
4. **Performance**: Current stock queries don't need to scan entire history
5. **Simplicity**: Three clear layers (operation → movement → balance) are easy to reason about
6. **Odoo-native**: Uses ORM, computed fields, sequences, security groups — no external dependencies
7. **Extensible**: Additional operation types, reports, or integrations can be added without changing the core model
8. **Hackathon-practical**: Not over-engineered; solves real inventory problems without unnecessary abstraction
