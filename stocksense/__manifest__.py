# -*- coding: utf-8 -*-
{
    'name': 'StockSense',
    'version': '17.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Centralized Inventory Management with Auditable Movement Ledger',
    'description': """
StockSense - Inventory Management System
=========================================

A centralized inventory management system providing full traceability
of stock movements across warehouses and locations through an auditable
movement ledger.

Features:
- Product & Category management
- Multi-warehouse support with hierarchical locations
- Receipt, Delivery, Internal Transfer, and Adjustment operations
- Append-only movement ledger for full auditability
- Hybrid stock balance (cached + movement-based)
- Reorder rules and low-stock detection
- Complete stock history reconstruction
    """,
    'author': 'StockSense Team',
    'website': 'https://github.com/stocksense',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/location_data.xml',
        'views/category_views.xml',
        'views/product_views.xml',
        'views/warehouse_views.xml',
        'views/location_views.xml',
        'views/operation_views.xml',
        'views/movement_views.xml',
        'views/stock_views.xml',
        'views/reorder_rule_views.xml',
        'views/menu.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
