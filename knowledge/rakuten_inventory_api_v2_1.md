# Rakuten Inventory API v2.1 Guide

## 1. Overview
InventoryAPI 2.1 is used to manage inventory, shipping lead times, and delivery lead times for shops after SKU migration.

## 2. Main Endpoints

### inventories.variants.get
Retrieve inventory for a specific manageNumber and variantId.
- **Endpoint**: `GET https://api.rms.rakuten.co.jp/es/2.1/inventories/manage-numbers/{manageNumber}/variants/{variantId}`
- **Authentication**: `Authorization: ESA Base64(serviceSecret:licenseKey)`

### Path Parameters
- **manageNumber**: Item Management Number (Item URL). Max 32 bytes. Allowed: `a-z, A-Z, 0-9, -, _`.
- **variantId**: SKU Management Number. Max 32 bytes. Allowed: `a-z, A-Z, 0-9, -, _`. (Note: Case sensitive).

## 3. Response Structure (Success)
```json
{
    "manageNumber": "mng1234",
    "variantId": "sku1",
    "quantity": 100,
    "operationLeadTime": {
        "normalDeliveryTimeId": 4,
        "backOrderDeliveryTimeId": 5
    },
    "shipFromIds": [3],
    "created": "2022-07-01T10:00:00+09:00",
    "updated": "2022-07-01T10:30:00+09:00"
}
```

## 4. Bulk Get (Multiple Items)
- **Endpoint**: `POST https://api.rms.rakuten.co.jp/es/2.1/inventories/bulk-get`
- **Body**:
```json
{
    "inventories": [
        { "manageNumber": "mng1234", "variantId": "sku1" },
        { "manageNumber": "mng5678", "variantId": "sku5" }
    ]
}
```

## 5. Variant List
Retrieve all variants for a manageNumber.
- **Endpoint**: `GET https://api.rms.rakuten.co.jp/es/2.1/inventories/variant-lists/manage-numbers/{manageNumber}`
