CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(100) NOT NULL,
    company_info JSON,
    saved_companies JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    post BOOLEAN DEFAULT FALSE,
user_info varchar(100)
);


CREATE TABLE orders (
    id VARCHAR(36) PRIMARY KEY,
    seller_id VARCHAR(36) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL,
    items TEXT NOT NULL,
    total DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at DATETIME NULL,
    FOREIGN KEY (seller_id) REFERENCES users(id),
    FOREIGN KEY (supplier_id) REFERENCES users(id)
);

CREATE TABLE chats (
    id VARCHAR(36) PRIMARY KEY,
    seller_id VARCHAR(36) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (seller_id) REFERENCES users(id),
    FOREIGN KEY (supplier_id) REFERENCES users(id)
) ENGINE=InnoDB;


CREATE TABLE messages (
    id VARCHAR(36) PRIMARY KEY,
    chat_id VARCHAR(36) NOT NULL,
    sender_id VARCHAR(36) NOT NULL,
    content TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chats(id),
    FOREIGN KEY (sender_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- Триггер для chats
DELIMITER $$
CREATE TRIGGER before_chats_insert
BEFORE INSERT ON chats
FOR EACH ROW
BEGIN
    IF NEW.id IS NULL THEN
        SET NEW.id = UUID();
    END IF;
END$$
DELIMITER ;

-- Триггер для messages
DELIMITER $$
CREATE TRIGGER before_messages_insert
BEFORE INSERT ON messages
FOR EACH ROW
BEGIN
    IF NEW.id IS NULL THEN
        SET NEW.id = UUID();
    END IF;
END$$
DELIMITER ;



ALTER TABLE messages 
ADD COLUMN is_read BOOLEAN DEFAULT FALSE;
