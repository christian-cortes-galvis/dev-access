-- Bootstrap del portal de copias. Ejecutar UNA VEZ como admin de MySQL en
-- ubuntu-docker (.87), después de publicar el puerto 3306 en la LAN.
--
-- Reemplazar CAMBIAR_CLAVE_FUERTE por una clave aleatoria y dejarla también en
-- /etc/backupcsr/web.env (0600 root). Nunca usar password vacío.

CREATE DATABASE IF NOT EXISTS backupcsr CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'backupcsr_web'@'192.168.0.49' IDENTIFIED BY 'CAMBIAR_CLAVE_FUERTE';

GRANT ALL PRIVILEGES ON backupcsr.* TO 'backupcsr_web'@'192.168.0.49';

FLUSH PRIVILEGES;
