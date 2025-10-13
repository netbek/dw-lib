CREATE TABLE table_1 (
    id bigint PRIMARY KEY,
    username text,
    age smallint,
    modified_at timestamp(6)
);

CREATE TABLE table_2 (
    id bigint PRIMARY KEY,
    longitude double precision,
    latitude double precision,
    is_secret boolean,
    modified_at timestamp(6)
);

CREATE TABLE table_3 (
    id bigint PRIMARY KEY,
    ts timestamp(6),
    modified_at timestamp(6)
);

INSERT INTO table_1 (id, username, age, modified_at) VALUES
(1, 'alice', 25, '2025-10-13 10:15:30.123456'),
(2, 'bob', 31, '2025-10-13 10:16:05.654321'),
(3, 'charlie', 29, '2025-10-13 10:17:42.987654');

INSERT INTO table_2 (id, longitude, latitude, is_secret, modified_at) VALUES
(1, 18.4233, -33.9189, false, '2025-10-13 11:00:00.111111'),
(2, -0.1278, 51.5074, true, '2025-10-13 11:05:30.222222'),
(3, 139.6917, 35.6895, false, '2025-10-13 11:10:45.333333');

INSERT INTO table_3 (id, ts, modified_at) VALUES
(1, '2025-10-13 09:00:00.000001', '2025-10-13 09:30:00.999999'),
(2, '2025-10-13 09:05:00.500000', '2025-10-13 09:35:10.888888'),
(3, '2025-10-13 09:10:00.250000', '2025-10-13 09:40:20.777777');
