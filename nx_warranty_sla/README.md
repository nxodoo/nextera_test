# Warranty / SLA Management (`nx_warranty_sla`)

Odoo 18 module for managing warranty/SLA templates and contracts across Sales, Products, Helpdesk, Contacts, and Portal.

## Features

- Warranty templates with duration types:
  - `months`
  - `fixed_dates`
  - `tickets_based`
- Product-level warranty assignment (templates selectable on product form)
- Automatic warranty contract creation from confirmed Sale Orders
- Usage tracking:
  - Minutes: allocated, used, remaining
  - Tickets: total, used, remaining
- Helpdesk integration for warranty consumption
- Contacts integration with warranty smart access
- Portal pages for customer warranty visibility
- Daily cron for lifecycle updates:
  - set `expired` when `end_date` is passed
  - set `need_to_be_extended` when usage exceeds threshold

## Required Apps

- Sales
- Contacts
- Helpdesk
- Portal
- Website
- eLearning (`website_slides`)
- Mail

## Installation

1. Place module under your addons path.
2. Update Apps List.
3. Install module `Warranty / SLA Management`.

## Basic Flow

1. Create a warranty template.
2. Open a product and enable `Has Warranty`.
3. Assign one or more warranty templates to the product.
4. Create a quotation/sale order with that product.
5. Confirm the sale order.
6. Open the `Warranty` smart button on SO to see created contracts.
7. Create helpdesk tickets and link/consume against warranty contracts.
8. Verify state transitions and remaining usage.

## Notes

- Contracts are created in `draft` by default.
- Ticket-based contracts derive ticket quota from sold quantity when linked to a sale order line.
- For date-based warranties, start/end dates from SO line are propagated when provided.
