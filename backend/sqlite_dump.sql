CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR NOT NULL UNIQUE,
    hashed_password VARCHAR NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP,
    last_updated_by INTEGER REFERENCES users(id),
    last_updated_at TIMESTAMP
);
INSERT INTO users (id,email,hashed_password,is_admin) VALUES
(1,'adithya@gmail.com','$2b$12$oCdqW7oHlQYNOF1EOQMGK.dJ.7NegkjZux3IyVFarDSlm8aztzzM6',TRUE),
(2,'akil@gmail.com','$2b$12$Xr5nUbVI1Snlnla1JE5GNOSl3YazLJ0wOUGm3a7W7ufzJdi1MQp3i',FALSE),
(3,'abc@gmail.com','$2b$12$hJWoQe8AqhmeBSl3nyWX6.vYZ3jivQO6de/8VEplqcGgwnnWfVnhe',FALSE);
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR NOT NULL,
    invoice_number VARCHAR,
    invoice_date VARCHAR,
    vendor_name VARCHAR,
    trn_vat_number VARCHAR,
    before_tax_amount VARCHAR,
    tax_amount VARCHAR,
    total VARCHAR,
    reviewed BOOLEAN DEFAULT FALSE,
    owner_id INTEGER NOT NULL REFERENCES users(id)
);
INSERT INTO invoices (id,file_path,invoice_number,invoice_date,vendor_name,trn_vat_number,before_tax_amount,tax_amount,total,reviewed,owner_id) VALUES
(1,'https://pub-82afcfc4d4894042a2a9b2f63ca6044a.r2.dev/ae0165107ba24ba08051876408d49419.pdf','126984136','31 Aug 2025','Careem Deliveries FZ LLC',NULL,'248.77','5224.26','5224.26',FALSE,1),
(2,'https://pub-82afcfc4d4894042a2a9b2f63ca6044a.r2.dev/a004dd654cd44b1eb80a4962ff831084.pdf','126984136','31 Aug 2025','Careem Deliveries FZ LLC',NULL,'248.77','5224.26','5224.26',FALSE,1),
(3,'https://pub-82afcfc4d4894042a2a9b2f63ca6044a.r2.dev/a4fe150eb8cb4c09a2c61cab9908543a.jpeg',NULL,'09-JAN-2021','Black Tulip Flowers LLC.',NULL,'12.50',NULL,NULL,FALSE,1),
(4,'https://pub-82afcfc4d4894042a2a9b2f63ca6044a.r2.dev/d60e97a5c56f4b4880faca3b38a88ae1.jpeg','2 137634',NULL,'TCO DISTRITION SERVICES Izco (BAL BRANCHE',NULL,'44.81','924.28','924.28',FALSE,1),
(5,'https://pub-82afcfc4d4894042a2a9b2f63ca6044a.r2.dev/b8f1c2d67808482f825d3cb79eacb8a9.jpeg','7488/2025',NULL,'AAL OMAIRA',NULL,'16.50','346.50','346.50',FALSE,1);

CREATE TABLE alembic_version (
    version_num VARCHAR(32) PRIMARY KEY
);
CREATE INDEX ix_users_id ON users (id);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_invoices_id ON invoices (id);
