-- ============================================================
-- SIDEC - Sistema de Certificados de Calibración
-- Base de datos: sidec_db | Server: sidecmexico
-- Schema principal con particionamiento por año
-- ============================================================

-- Extensión para búsqueda de texto completo
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- TABLA: tipos_magnitud (catálogo)
-- ============================================================
CREATE TABLE IF NOT EXISTS tipos_magnitud (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    descripcion TEXT
);

INSERT INTO tipos_magnitud (nombre) VALUES
    ('DIMENSIONAL'),
    ('ELÉCTRICA'),
    ('MASA'),
    ('TEMPERATURA'),
    ('PRESIÓN'),
    ('FUERZA'),
    ('VOLUMEN'),
    ('OTRA')
ON CONFLICT DO NOTHING;

-- ============================================================
-- TABLA: certificados (particionada por año de emisión)
-- ============================================================
CREATE TABLE IF NOT EXISTS certificados (
    id                      BIGSERIAL,
    -- Identificación del certificado
    numero_informe          VARCHAR(50)  NOT NULL,          -- Ej: LMD-143-25
    anio_emision            SMALLINT     NOT NULL,          -- Clave de partición

    -- Datos del cliente
    nombre_cliente          VARCHAR(255),
    direccion               TEXT,
    atencion_a              VARCHAR(255),

    -- Datos del instrumento
    descripcion_instrumento VARCHAR(255),
    alcance                 TEXT,
    numero_serie            VARCHAR(100),
    identificacion          VARCHAR(100),
    modelo                  VARCHAR(100),
    marca                   VARCHAR(100),
    magnitud_evaluada       VARCHAR(100),

    -- Resultados
    resultado_calibracion   TEXT,
    incertidumbre           TEXT,

    -- Condiciones ambientales
    temperatura             VARCHAR(50),
    humedad_relativa        VARCHAR(50),

    -- Fechas
    fecha_recepcion         DATE,
    fecha_calibracion       DATE,
    fecha_emision           DATE,

    -- Método y lugar
    metodo_utilizado        TEXT,
    lugar_calibracion       VARCHAR(255),

    -- Personal
    calibrado_por           VARCHAR(255),
    aprobado_por            VARCHAR(255),

    -- Metadatos del sistema
    ruta_archivo_origen     TEXT,                           -- ruta del .xlsx original
    fecha_importacion       TIMESTAMPTZ DEFAULT NOW(),
    importado_por           VARCHAR(100),
    activo                  BOOLEAN DEFAULT TRUE,

    PRIMARY KEY (id, anio_emision)
) PARTITION BY RANGE (anio_emision);

-- ============================================================
-- PARTICIONES POR AÑO (2017 al 2026)
-- ============================================================
CREATE TABLE IF NOT EXISTS certificados_2017 PARTITION OF certificados
    FOR VALUES FROM (2017) TO (2018);

CREATE TABLE IF NOT EXISTS certificados_2018 PARTITION OF certificados
    FOR VALUES FROM (2018) TO (2019);

CREATE TABLE IF NOT EXISTS certificados_2019 PARTITION OF certificados
    FOR VALUES FROM (2019) TO (2020);

CREATE TABLE IF NOT EXISTS certificados_2020 PARTITION OF certificados
    FOR VALUES FROM (2020) TO (2021);

CREATE TABLE IF NOT EXISTS certificados_2021 PARTITION OF certificados
    FOR VALUES FROM (2021) TO (2022);

CREATE TABLE IF NOT EXISTS certificados_2022 PARTITION OF certificados
    FOR VALUES FROM (2022) TO (2023);

CREATE TABLE IF NOT EXISTS certificados_2023 PARTITION OF certificados
    FOR VALUES FROM (2023) TO (2024);

CREATE TABLE IF NOT EXISTS certificados_2024 PARTITION OF certificados
    FOR VALUES FROM (2024) TO (2025);

CREATE TABLE IF NOT EXISTS certificados_2025 PARTITION OF certificados
    FOR VALUES FROM (2025) TO (2026);

CREATE TABLE IF NOT EXISTS certificados_2026 PARTITION OF certificados
    FOR VALUES FROM (2026) TO (2027);

-- Partición para datos sin año definido o futuros
CREATE TABLE IF NOT EXISTS certificados_otros PARTITION OF certificados
    DEFAULT;

-- ============================================================
-- ÍNDICES (por partición principal, se heredan)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_cert_numero_informe
    ON certificados (numero_informe);

CREATE INDEX IF NOT EXISTS idx_cert_cliente_trgm
    ON certificados USING GIN (nombre_cliente gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_cert_numero_serie
    ON certificados (numero_serie);

CREATE INDEX IF NOT EXISTS idx_cert_identificacion
    ON certificados (identificacion);

CREATE INDEX IF NOT EXISTS idx_cert_fecha_emision
    ON certificados (fecha_emision);

CREATE INDEX IF NOT EXISTS idx_cert_anio
    ON certificados (anio_emision);

CREATE INDEX IF NOT EXISTS idx_cert_marca_trgm
    ON certificados USING GIN (marca gin_trgm_ops);

-- ============================================================
-- TABLA: usuarios
-- ============================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    usuario         VARCHAR(50)  NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    rol             VARCHAR(50)  NOT NULL DEFAULT 'certificaciones',
                    -- roles: 'admin' | 'calidad' | 'reportes' | 'certificaciones'
    departamento    VARCHAR(100),
    activo          BOOLEAN DEFAULT TRUE,
    creado_en       TIMESTAMPTZ DEFAULT NOW(),
    ultimo_acceso   TIMESTAMPTZ
);

-- ============================================================
-- TABLA: auditoria (registro de cambios)
-- ============================================================
CREATE TABLE IF NOT EXISTS auditoria (
    id              BIGSERIAL PRIMARY KEY,
    usuario_id      INTEGER REFERENCES usuarios(id),
    accion          VARCHAR(50) NOT NULL,   -- 'INSERT' | 'UPDATE' | 'DELETE' | 'VIEW'
    tabla           VARCHAR(50),
    registro_id     BIGINT,
    datos_antes     JSONB,
    datos_despues   JSONB,
    ip_origen       VARCHAR(45),
    creado_en       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria (usuario_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha   ON auditoria (creado_en);

-- ============================================================
-- TABLA: importaciones (historial de cargas masivas)
-- ============================================================
CREATE TABLE IF NOT EXISTS importaciones (
    id                  SERIAL PRIMARY KEY,
    usuario_id          INTEGER REFERENCES usuarios(id),
    carpeta_origen      TEXT,
    total_archivos      INTEGER DEFAULT 0,
    exitosos            INTEGER DEFAULT 0,
    fallidos            INTEGER DEFAULT 0,
    errores             JSONB,
    iniciado_en         TIMESTAMPTZ DEFAULT NOW(),
    finalizado_en       TIMESTAMPTZ,
    estado              VARCHAR(20) DEFAULT 'en_proceso'
                        -- 'en_proceso' | 'completado' | 'con_errores'
);

-- ============================================================
-- USUARIOS ADMIN
-- ============================================================

-- ► Usuario principal: Adminappsidec / Adminsidec
--   Hash generado y verificado con bcrypt.compare() = true
INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento)
VALUES (
    'Administrador App SIDEC',
    'Adminappsidec',
    '$2b$10$noUwyXbAGn04LMmNccrw6.tp8FKzjSB/U68T68cDug6Rg/VYPqpIq',
    'admin',
    'Administración'
) ON CONFLICT (usuario) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        rol           = 'admin',
        activo        = TRUE;

-- ► Usuario heredado: Administrador_Sidec / Adminsidec  (mismo hash, misma contraseña)
INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento)
VALUES (
    'Administrador SIDEC',
    'Administrador_Sidec',
    '$2b$10$noUwyXbAGn04LMmNccrw6.tp8FKzjSB/U68T68cDug6Rg/VYPqpIq',
    'admin',
    'Administración'
) ON CONFLICT (usuario) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        rol           = 'admin',
        activo        = TRUE;

-- ============================================================
-- VISTA: resumen por año (útil para el panel)
-- ============================================================
CREATE OR REPLACE VIEW resumen_por_anio AS
SELECT
    anio_emision,
    COUNT(*)                            AS total_certificados,
    COUNT(DISTINCT nombre_cliente)      AS total_clientes,
    COUNT(DISTINCT marca)               AS total_marcas,
    MIN(fecha_emision)                  AS primera_emision,
    MAX(fecha_emision)                  AS ultima_emision
FROM certificados
WHERE activo = TRUE
GROUP BY anio_emision
ORDER BY anio_emision DESC;

-- ============================================================
-- FIN DEL SCHEMA
-- ============================================================
