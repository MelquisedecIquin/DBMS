CREATE DATABASE IF NOT EXISTS earthquake_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE earthquake_db;

CREATE TABLE IF NOT EXISTS fault_lines (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    name                 VARCHAR(255)   NOT NULL,
    slip_type            VARCHAR(100),
    strike_slip_rate     VARCHAR(50),
    net_slip_rate        VARCHAR(50),
    activity_confidence  VARCHAR(100),
    epistemic_quality    VARCHAR(100),
    average_dip          VARCHAR(50),
    dip_dir              VARCHAR(50),
    upper_seis_depth     VARCHAR(50),
    lower_seis_depth     VARCHAR(50),
    average_rake         VARCHAR(50),
    notes                TEXT,
    reference            TEXT,
    geom_json            LONGTEXT,          
    bbox_min_lat         DOUBLE,
    bbox_max_lat         DOUBLE,
    bbox_min_lng         DOUBLE,
    bbox_max_lng         DOUBLE,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_bbox (bbox_min_lat, bbox_max_lat, bbox_min_lng, bbox_max_lng)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS earthquakes (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    date_time_ph         DATETIME       NOT NULL,
    latitude             DOUBLE         NOT NULL,
    longitude            DOUBLE         NOT NULL,
    depth_km             DOUBLE,
    magnitude            DOUBLE         NOT NULL,
    location             VARCHAR(512),
    specific_location    VARCHAR(255),
    general_location     VARCHAR(255),
    nearest_fault_id     INT,
    risk_level           ENUM('Low','Moderate','High','Very High') GENERATED ALWAYS AS (
                             CASE
                                 WHEN magnitude < 4.0 THEN 'Low'
                                 WHEN magnitude < 5.0 THEN 'Moderate'
                                 WHEN magnitude < 7.0 THEN 'High'
                                 ELSE 'Very High'
                             END
                         ) STORED,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_fault FOREIGN KEY (nearest_fault_id) REFERENCES fault_lines(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_latlon      (latitude, longitude),
    INDEX idx_datetime    (date_time_ph),
    INDEX idx_magnitude   (magnitude),
    INDEX idx_risk        (risk_level),
    INDEX idx_gen_loc     (general_location),
    INDEX idx_spec_loc    (specific_location)
) ENGINE=InnoDB;


CREATE TABLE IF NOT EXISTS audit_log (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    table_name  VARCHAR(64)  NOT NULL,
    record_id   INT          NOT NULL,
    action      ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    changed_by  VARCHAR(128) DEFAULT 'system',
    changed_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    old_values  JSON,
    new_values  JSON
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_earthquake_details AS
SELECT
    e.id,
    e.date_time_ph,
    e.latitude,
    e.longitude,
    e.depth_km,
    e.magnitude,
    e.risk_level,
    e.location,
    e.specific_location,
    e.general_location,
    f.name  AS fault_name,
    f.slip_type AS fault_slip_type
FROM earthquakes e
LEFT JOIN fault_lines f ON e.nearest_fault_id = f.id;
