# Código para 
CREATE DATABASE IF NOT EXISTS monitoreo_acustico 
    DEFAULT CHARACTER SET utf8mb4 
    DEFAULT COLLATE utf8mb4_general_ci;

USE monitoreo_acustico;

CREATE TABLE IF NOT EXISTS historial_llanto (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    probabilidad FLOAT NOT NULL,
    es_llanto BOOLEAN NOT NULL,
    origen VARCHAR(50) DEFAULT 'auto',
    duracion_seg FLOAT DEFAULT 3.0,
    INDEX idx_timestamp (timestamp),
    INDEX idx_llanto (es_llanto),
    INDEX idx_origen (origen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;