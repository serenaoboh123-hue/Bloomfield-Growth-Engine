CREATE DATABASE bloomfield_growth_engine;
USE bloomfield_growth_engine;

CREATE TABLE channels (
    channel_id   INT AUTO_INCREMENT PRIMARY KEY,
    channel_name VARCHAR(50) NOT NULL UNIQUE
    
);
 
INSERT INTO channels (channel_name) VALUES
('Google Ads'), ('Meta Ads'), ('Email'), ('Organic');

CREATE TABLE staging_orders (
    transaction_id   VARCHAR(20),
    customer_id      VARCHAR(20),
    order_timestamp  VARCHAR(30),
    channel          VARCHAR(30),
    revenue          VARCHAR(20),
    product          VARCHAR(100)
);

CREATE TABLE staging_spend (
    spend_date     VARCHAR(20),
    channel        VARCHAR(30),
    campaign_name  VARCHAR(100),
    raw_spend      VARCHAR(20),
    net_spend      VARCHAR(20)
);
 
CREATE TABLE staging_alerts (
    alert_date               VARCHAR(20),
    channel                  VARCHAR(30),
    metric                   VARCHAR(30),
    old_alert                VARCHAR(10),
    current_period_value     VARCHAR(20),
    comparison_period_value  VARCHAR(20)
);

CREATE TABLE orders (
    transaction_id   VARCHAR(20) PRIMARY KEY,
    customer_id      VARCHAR(20) NOT NULL,
    order_timestamp  DATETIME NOT NULL,
    channel_id       INT NOT NULL,
    revenue          DECIMAL(10,2) NULL,   -- NULL kept: order happened, revenue unknown
    product          VARCHAR(100) NOT NULL,
    CONSTRAINT fk_orders_channel FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);
CREATE INDEX idx_orders_timestamp    ON orders(order_timestamp);
CREATE INDEX idx_orders_channel      ON orders(channel_id);
CREATE INDEX idx_orders_channel_date ON orders(channel_id, order_timestamp);
 
CREATE TABLE spend (
    spend_id       INT AUTO_INCREMENT PRIMARY KEY,   -- no natural key exists in this file
    spend_date     DATE NOT NULL,
    channel_id     INT NOT NULL,
    campaign_name  VARCHAR(100) NOT NULL,
    raw_spend      DECIMAL(10,2) NOT NULL,
    net_spend      DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_spend_channel FOREIGN KEY (channel_id) REFERENCES channels(channel_id),
    CONSTRAINT chk_spend_nonneg CHECK (raw_spend >= 0 AND net_spend >= 0)
);
CREATE INDEX idx_spend_date          ON spend(spend_date);
CREATE INDEX idx_spend_channel       ON spend(channel_id);
CREATE INDEX idx_spend_channel_date  ON spend(channel_id, spend_date);
 
CREATE TABLE alerts (
    alert_id                  INT AUTO_INCREMENT PRIMARY KEY,  -- no natural key here either
    alert_date                DATE NOT NULL,
    channel_id                INT NOT NULL,
    metric                    VARCHAR(30) NOT NULL,
    old_alert                 TINYINT(1) NOT NULL,  -- Yes/No as stored; meaning is ambiguous, kept as-is
    current_period_value      DECIMAL(10,2) NOT NULL,
    comparison_period_value   DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_alerts_channel FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);
CREATE INDEX idx_alerts_date    ON alerts(alert_date);
CREATE INDEX idx_alerts_channel ON alerts(channel_id);
CREATE INDEX idx_alerts_metric  ON alerts(metric);

CREATE TABLE data_quality_log (
    log_id         INT AUTO_INCREMENT PRIMARY KEY,
    source_table   VARCHAR(30) NOT NULL,
    issue_type     VARCHAR(50) NOT NULL,
    row_identifier VARCHAR(100),
    detail         TEXT,
    logged_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);


INSERT INTO data_quality_log (source_table, issue_type, row_identifier, detail)
SELECT 'staging_orders', 'exact_duplicate', transaction_id,
       'Duplicate row — same transaction_id and identical values; extra occurrence excluded on load'
FROM (
    SELECT transaction_id,
           ROW_NUMBER() OVER (
               PARTITION BY transaction_id, customer_id, order_timestamp, channel, revenue, product
               ORDER BY transaction_id
           ) AS rn
    FROM staging_orders
) t
WHERE rn > 1;

INSERT INTO data_quality_log (source_table, issue_type, row_identifier, detail)
SELECT 'staging_orders', 'null_revenue', transaction_id,
       'Revenue missing — order kept for volume analysis, excluded automatically from revenue sums'
FROM staging_orders
WHERE revenue IS NULL OR TRIM(revenue) = '';
 
-- 6.3 Spend: exact duplicate rows (same date+channel+campaign+amounts)
INSERT INTO data_quality_log (source_table, issue_type, row_identifier, detail)
SELECT 'staging_spend', 'exact_duplicate', CONCAT(spend_date, '|', channel, '|', campaign_name),
       'Duplicate spend row — same date/channel/campaign with identical amounts; extra occurrence excluded on load'
FROM (
    SELECT spend_date, channel, campaign_name,
           ROW_NUMBER() OVER (
               PARTITION BY spend_date, channel, campaign_name, raw_spend, net_spend
               ORDER BY spend_date
           ) AS rn
    FROM staging_spend
) t
WHERE rn > 1;

INSERT INTO data_quality_log (source_table, issue_type, row_identifier, detail)
SELECT 'staging_spend', 'zero_spend_suspicious', CONCAT(spend_date, '|', channel, '|', campaign_name),
       'Raw Spend and Net Spend both zero — verify whether campaign was paused that day'
FROM staging_spend
WHERE CAST(raw_spend AS DECIMAL(10,2)) = 0;

INSERT INTO orders (transaction_id, customer_id, order_timestamp, channel_id, revenue, product)
SELECT
    s.transaction_id,
    s.customer_id,
    STR_TO_DATE(s.order_timestamp, '%d/%m/%Y %H:%i'),
    c.channel_id,
    CASE WHEN TRIM(s.revenue) = '' THEN NULL ELSE CAST(s.revenue AS DECIMAL(10,2)) END,
    TRIM(s.product)
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY transaction_id, customer_id, order_timestamp, channel, revenue, product
               ORDER BY transaction_id
           ) AS rn
    FROM staging_orders
) s
 LEFT JOIN channels c ON c.channel_name = CASE UPPER(TRIM(s.channel))
    WHEN 'GOOGLE ADS' THEN 'Google Ads'
    WHEN 'META ADS'   THEN 'Meta Ads'
    WHEN 'EMAIL'      THEN 'Email'
    WHEN 'ORGANIC'    THEN 'Organic'
END
WHERE s.rn = 1;


INSERT INTO spend (spend_date, channel_id, campaign_name, raw_spend, net_spend)
SELECT
    STR_TO_DATE(TRIM(s.spend_date), '%d/%m/%Y'),
    c.channel_id,
    TRIM(s.campaign_name),
    CAST(s.raw_spend AS DECIMAL(10,2)),
    CAST(s.net_spend AS DECIMAL(10,2))
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY spend_date, channel, campaign_name, raw_spend, net_spend
               ORDER BY spend_date
           ) AS rn
    FROM staging_spend
) s
JOIN channels c ON c.channel_name = CASE UPPER(REPLACE(TRIM(s.channel), '_', ' '))
    WHEN 'GOOGLE ADS' THEN 'Google Ads'
    WHEN 'META ADS'   THEN 'Meta Ads'
END
WHERE s.rn = 1;

INSERT INTO alerts (alert_date, channel_id, metric, old_alert, current_period_value, comparison_period_value)
SELECT
    STR_TO_DATE(TRIM(s.alert_date), '%d/%m/%Y'),
    c.channel_id,
    TRIM(s.metric),
    CASE WHEN UPPER(TRIM(s.old_alert)) = 'YES' THEN 1 ELSE 0 END,
    CAST(s.current_period_value AS DECIMAL(10,2)),
    CAST(s.comparison_period_value AS DECIMAL(10,2))
FROM staging_alerts s
JOIN channels c ON c.channel_name = TRIM(s.channel);


SELECT 'staging_orders' AS tbl, COUNT(*) AS row_count FROM staging_orders
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'staging_spend', COUNT(*) FROM staging_spend
UNION ALL SELECT 'spend', COUNT(*) FROM spend
UNION ALL SELECT 'staging_alerts', COUNT(*) FROM staging_alerts
UNION ALL SELECT 'alerts', COUNT(*) FROM alerts;



SELECT transaction_id, COUNT(*) FROM orders GROUP BY transaction_id HAVING COUNT(*) > 1;

SELECT
    (SELECT COUNT(*) FROM orders WHERE customer_id IS NULL) AS null_customer,
    (SELECT COUNT(*) FROM orders WHERE product IS NULL)     AS null_product,
    (SELECT COUNT(*) FROM orders WHERE revenue IS NULL)     AS null_revenue;
    
    SELECT * FROM orders WHERE order_timestamp < '2020-01-01' OR order_timestamp > NOW();
SELECT * FROM spend  WHERE spend_date < '2020-01-01' OR spend_date > CURDATE();

SELECT * FROM orders WHERE revenue < 0;
SELECT * FROM spend  WHERE raw_spend < 0 OR net_spend < 0;

SELECT DISTINCT channel FROM staging_orders
WHERE UPPER(TRIM(channel)) NOT IN ('GOOGLE ADS','META ADS','EMAIL','ORGANIC');
SELECT DISTINCT metric FROM alerts WHERE metric NOT IN ('ROAS','CPA','CTR','Conversion Rate');

SELECT transaction_id, customer_id, order_timestamp, channel_id, revenue, product, COUNT(*)
FROM orders GROUP BY transaction_id, customer_id, order_timestamp, channel_id, revenue, product
HAVING COUNT(*) > 1;

SELECT spend_date, channel_id, campaign_name, raw_spend, net_spend, COUNT(*)
FROM spend GROUP BY spend_date, channel_id, campaign_name, raw_spend, net_spend
HAVING COUNT(*) > 1;

SELECT o.channel_id FROM orders o LEFT JOIN channels c ON o.channel_id = c.channel_id WHERE c.channel_id IS NULL;
SELECT s.channel_id FROM spend  s LEFT JOIN channels c ON s.channel_id = c.channel_id WHERE c.channel_id IS NULL;

SELECT * FROM orders WHERE revenue > (SELECT AVG(revenue) + 3 * STDDEV(revenue) FROM orders);
SELECT COUNT(*) AS zero_spend_rows FROM spend WHERE raw_spend = 0;

SELECT * FROM spend WHERE net_spend > raw_spend;

SELECT issue_type, COUNT(*) AS flagged_rows FROM data_quality_log GROUP BY issue_type;

CREATE OR REPLACE VIEW vw_daily_revenue_by_channel AS
SELECT DATE(o.order_timestamp) AS order_date, c.channel_name,
       SUM(o.revenue) AS total_revenue, COUNT(*) AS order_count
FROM orders o
JOIN channels c ON o.channel_id = c.channel_id
GROUP BY DATE(o.order_timestamp), c.channel_name;

CREATE OR REPLACE VIEW vw_daily_spend_by_channel AS
SELECT s.spend_date, c.channel_name,
       SUM(s.raw_spend) AS total_raw_spend, SUM(s.net_spend) AS total_net_spend
FROM spend s
JOIN channels c ON s.channel_id = c.channel_id
GROUP BY s.spend_date, c.channel_name;

-- 10.1 Daily revenue, spend, and ROAS by channel (safe join — both sides pre-aggregated)
SELECT
    r.order_date,
    r.channel_name,
    r.total_revenue,
    s.total_net_spend,
    ROUND(r.total_revenue / NULLIF(s.total_net_spend, 0), 2) AS roas
FROM vw_daily_revenue_by_channel r
JOIN vw_daily_spend_by_channel s
    ON r.order_date = s.spend_date AND r.channel_name = s.channel_name
ORDER BY r.order_date, r.channel_name;

SELECT
    channel_name,
    DATE_FORMAT(order_date, '%Y-%m') AS month,
    SUM(total_revenue) AS monthly_revenue
FROM vw_daily_revenue_by_channel
GROUP BY channel_name, DATE_FORMAT(order_date, '%Y-%m')
ORDER BY channel_name, month;

SELECT
    c.channel_name,
    COALESCE(SUM(o.revenue), 0) AS total_revenue,
    (SELECT COALESCE(SUM(net_spend), 0) FROM spend WHERE channel_id = c.channel_id) AS total_spend,
    ROUND(
        COALESCE(SUM(o.revenue), 0) /
        NULLIF((SELECT SUM(net_spend) FROM spend WHERE channel_id = c.channel_id), 0)
    , 2) AS overall_roas
FROM channels c
LEFT JOIN orders o ON o.channel_id = c.channel_id
GROUP BY c.channel_name;

SELECT
    a.alert_date, c.channel_name, a.metric,
    a.current_period_value, a.comparison_period_value,
    r.total_revenue AS revenue_that_day
FROM alerts a
JOIN channels c ON a.channel_id = c.channel_id
LEFT JOIN vw_daily_revenue_by_channel r
    ON r.order_date = a.alert_date AND r.channel_name = c.channel_name
ORDER BY a.alert_date;































 

 