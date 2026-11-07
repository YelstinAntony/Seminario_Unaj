import os
import json
import qrcode
from flask import Flask, render_template, request, jsonify, send_file
import csv
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import smtplib
from email.message import EmailMessage

app = Flask(__name__)

DB_FILE = "asistentes.json"
STATIC_DIR = "static"

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Tus credenciales institucionales de la UNAJ (soportan variables de entorno en la nube)
EMAIL_REMITE = os.environ.get("EMAIL_REMITE", "2023107039.est@unaj.edu.pe")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "ojdg wgnm zluk bgbj")  # Tus 16 dígitos de Google
SMTP_TIMEOUT = 8  # Segundos máximos de espera para evitar bloqueos de Gunicorn en Render


def asegurar_qr_fisico(dni):
    """Garantiza que el archivo PNG del QR exista en static/ y devuelve su ruta y URL."""
    qr_filename = f"qr_{dni}.png"
    qr_path = os.path.join(STATIC_DIR, qr_filename)
    if not os.path.exists(qr_path):
        img = qrcode.make(str(dni))
        img.save(qr_path)
    return qr_path, f"/static/{qr_filename}"


def cargar_datos():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    # Normalizar registros para evitar KeyError en bases de datos antiguas
    cambios = False
    for a in datos:
        dni = str(a.get("dni", "")).strip()
        a["dni"] = dni
        a.setdefault("nombre", "Sin nombre")
        a.setdefault("email", "")
        a.setdefault("escuela", "No especificada")
        a.setdefault("semestre", "N/A")
        a.setdefault("asistio", False)
        a.setdefault("hora_ingreso", None)

        if not a.get("qr_url") and dni:
            a["qr_url"] = f"/static/qr_{dni}.png"
            cambios = True
        if "certificado_url" not in a:
            a["certificado_url"] = f"/static/certificado_{dni}.pdf" if a.get("asistio") and dni else None
            cambios = True

    if cambios:
        guardar_datos(datos)

    return datos


def guardar_datos(datos):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


# 📧 Función segura para enviar el Código QR por correo
def enviar_correo_qr(destinatario, nombre, qr_path):
    try:
        msg = EmailMessage()
        msg['Subject'] = "🎓 Tu Código QR de Acceso - Seminario UNAJ"
        msg['From'] = EMAIL_REMITE
        msg['To'] = destinatario

        cuerpo = (
            f"Estimado(a) {nombre},\n\n"
            "¡Gracias por inscribirte al Seminario 'Hostigamiento Sexual y la Prevención de Actos de Corrupción' de la UNAJ!\n\n"
            "Adjunto a este correo encontrarás tu código QR personal de acceso, el cual deberás presentar en la puerta del Auditorio Magno el 13 de noviembre de 2026 a las 11:00 a.m.\n\n"
            "¡Te esperamos!"
        )
        msg.set_content(cuerpo)

        with open(qr_path, 'rb') as f:
            file_data = f.read()

        msg.add_attachment(file_data, maintype='image', subtype='png', filename="MiCodigoQR_UNAJ.png")

        # Conexión SMTP segura con timeout y manejo de errores
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(EMAIL_REMITE, EMAIL_PASSWORD)
            smtp.send_message(msg)

        return True
    except Exception as e:
        print(f"❌ Error al enviar correo de QR: {e}")
        return False


def _cargar_fuente(nombres_fuentes, size):
    """Carga la primera fuente TrueType disponible (Windows/Linux) o usa la fuente por defecto."""
    for font_name in nombres_fuentes:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# 🎨 Generar certificado en PDF oficial del Seminario UNAJ
def generar_certificado_pdf(nombre, dni, escuela, semestre):
    cert_width, cert_height = 1200, 800
    image = Image.new("RGB", (cert_width, cert_height), color="#fcfcfc")
    draw = ImageDraw.Draw(image)

    draw.rectangle([40, 40, cert_width - 40, cert_height - 40], outline="#0d47a1", width=6)
    draw.rectangle([55, 55, cert_width - 55, cert_height - 55], outline="#90caf9", width=2)

    fuentes_regulares = [
        "arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    fuentes_negrita = [
        "arialbd.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]

    font_titulo = _cargar_fuente(fuentes_negrita, 42)
    font_sub = _cargar_fuente(fuentes_regulares, 20)
    font_nombre = _cargar_fuente(fuentes_negrita, 42)
    font_info = _cargar_fuente(fuentes_regulares, 18)

    draw.text((cert_width / 2, 110), "UNIVERSIDAD NACIONAL DE JULIACA", fill="#0d47a1", anchor="mm", font=font_sub)
    draw.text((cert_width / 2, 170), "CERTIFICADO DE PARTICIPACIÓN", fill="#0d47a1", anchor="mm", font=font_titulo)
    draw.text((cert_width / 2, 230), "Seminario: Hostigamiento Sexual y la Prevención de Actos de Corrupción", fill="#1976d2", anchor="mm", font=font_sub)

    draw.text((cert_width / 2, 320), "Otorgado oficialmente a:", fill="#555555", anchor="mm", font=font_sub)
    draw.text((cert_width / 2, 390), nombre.upper(), fill="#111111", anchor="mm", font=font_nombre)
    draw.line([300, 445, cert_width - 300, 445], fill="#0d47a1", width=3)

    info_detalle = f"Escuela / Categoría: {escuela}"
    if semestre and semestre != "N/A":
        info_detalle += f" | Semestre: {semestre}"

    draw.text((cert_width / 2, 490), info_detalle, fill="#333333", anchor="mm", font=font_sub)

    texto_desc = "Por su asistencia y participación en el evento realizado el 13 de noviembre del 2026\nen el Auditorio Magno de la UNAJ."
    draw.text((cert_width / 2, 560), texto_desc, fill="#444444", anchor="mm", font=font_info, align="center")

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    draw.text((250, 710), f"DNI / Código: {dni}", fill="#333333", anchor="mm", font=font_info)
    draw.text((cert_width - 250, 710), f"Fecha de emisión: {fecha_hoy}", fill="#333333", anchor="mm", font=font_info)

    cert_filename = f"certificado_{dni}.pdf"
    cert_path = os.path.join(STATIC_DIR, cert_filename)
    image.save(cert_path, "PDF", resolution=100.0)

    return cert_path, f"/static/{cert_filename}"


@app.route("/")
def index():
    return render_template("registro.html")


@app.route("/api/buscar", methods=["POST"])
def buscar():
    data = request.get_json(silent=True) or {}
    dni = str(data.get("dni", "")).strip()
    asistentes = cargar_datos()

    for a in asistentes:
        if a["dni"] == dni:
            # Asegurar que el QR físico y su URL existan
            _, qr_url = asegurar_qr_fisico(dni)
            a["qr_url"] = qr_url
            return jsonify({"success": True, "usuario": a})

    return jsonify({"success": False, "message": "No se encontró ninguna inscripción con este DNI o código."})


@app.route("/api/registrar", methods=["POST"])
def registrar():
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    dni = str(data.get("dni", "")).strip()
    email = str(data.get("email", "")).strip()
    escuela = str(data.get("escuela", "")).strip()
    semestre = str(data.get("semestre", "N/A")).strip() or "N/A"

    if not nombre or not dni or not email or not escuela:
        return jsonify({"success": False, "message": "Por favor completa todos los campos obligatorios."})

    asistentes = cargar_datos()

    # Generar la imagen QR física si no existe
    qr_path, qr_url_path = asegurar_qr_fisico(dni)

    # Intentar enviar el correo de forma segura (si falla la red, la app continúa sin romperse)
    correo_enviado = enviar_correo_qr(email, nombre, qr_path)

    usuario_existente = None
    for a in asistentes:
        if a["dni"] == dni:
            usuario_existente = a
            break

    if usuario_existente:
        usuario_existente["nombre"] = nombre
        usuario_existente["email"] = email
        usuario_existente["escuela"] = escuela
        usuario_existente["semestre"] = semestre
        usuario_existente["qr_url"] = qr_url_path
        if usuario_existente.get("asistio"):
            _, cert_url = generar_certificado_pdf(nombre, dni, escuela, semestre)
            usuario_existente["certificado_url"] = cert_url
        guardar_datos(asistentes)

        msg_correo = " y se ha reenviado a tu correo electrónico 📧" if correo_enviado else " (Inscripción actualizada, pero el correo no pudo enviarse por restricciones de red)."
        return jsonify({
            "success": True,
            "tipo": "actualizado",
            "message": f"¡Datos actualizados correctamente{msg_correo}!",
            "qr_url": qr_url_path
        })

    nuevo_asistente = {
        "dni": dni,
        "nombre": nombre,
        "email": email,
        "escuela": escuela,
        "semestre": semestre,
        "asistio": False,
        "hora_ingreso": None,
        "qr_url": qr_url_path,
        "certificado_url": None
    }
    asistentes.append(nuevo_asistente)
    guardar_datos(asistentes)

    msg_correo = " ¡Y te lo hemos enviado a tu correo electrónico 📧!" if correo_enviado else " (Inscripción exitosa. Puedes descargar tu código QR directamente desde esta pantalla)."
    return jsonify({
        "success": True,
        "tipo": "nuevo",
        "message": f"¡Inscripción exitosa al Seminario UNAJ!{msg_correo}",
        "qr_url": qr_url_path
    })


@app.route("/escaner")
def escaner():
    return render_template("escaner.html")


@app.route("/admin")
def admin():
    asistentes = cargar_datos()
    for a in asistentes:
        if a.get("asistio"):
            cert_path = os.path.join(STATIC_DIR, f"certificado_{a['dni']}.pdf")
            if not os.path.exists(cert_path):
                _, cert_url = generar_certificado_pdf(a["nombre"], a["dni"], a["escuela"], a["semestre"])
                a["certificado_url"] = cert_url
    return render_template("admin.html", asistentes=asistentes)


@app.route("/api/verificar", methods=["POST"])
def verificar():
    data = request.get_json(silent=True) or {}
    dni_escaneado = str(data.get("codigo", "")).strip()

    asistentes = cargar_datos()
    for a in asistentes:
        if a["dni"] == dni_escaneado:
            if a["asistio"]:
                return jsonify({
                    "success": False,
                    "tipo": "duplicado",
                    "message": f"⚠️ ATENCIÓN: {a['nombre']} ya ingresó anteriormente."
                })

            cert_path, cert_url = generar_certificado_pdf(a["nombre"], a["dni"], a["escuela"], a["semestre"])

            hora_actual = datetime.now().strftime("%H:%M:%S")
            a["asistio"] = True
            a["hora_ingreso"] = hora_actual
            a["certificado_url"] = cert_url
            guardar_datos(asistentes)

            return jsonify({
                "success": True,
                "tipo": "nuevo",
                "message": f"✅ ¡ACCESO AUTORIZADO!\n{a['nombre']}\n(Ingreso: {hora_actual})"
            })

    return jsonify({
        "success": False,
        "tipo": "error",
        "message": "❌ Código o DNI no encontrado en el sistema."
    })


@app.route("/api/enviar-certificado-individual", methods=["POST"])
def enviar_certificado_individual():
    data = request.get_json(silent=True) or {}
    dni = str(data.get("dni", "")).strip()

    asistentes = cargar_datos()
    for a in asistentes:
        if a["dni"] == dni:
            if not a["asistio"]:
                return jsonify({"success": False, "message": "El asistente aún no ha marcado asistencia."})

            cert_path, cert_url = generar_certificado_pdf(a["nombre"], a["dni"], a["escuela"], a["semestre"])
            a["certificado_url"] = cert_url
            guardar_datos(asistentes)

            try:
                msg = EmailMessage()
                msg['Subject'] = "🎓 Certificado - Seminario UNAJ"
                msg['From'] = EMAIL_REMITE
                msg['To'] = a["email"]

                msg.set_content(f"Estimado(a) {a['nombre']},\n\nAdjunto encontrará su certificado oficial de participación en el Seminario 'Hostigamiento Sexual y la Prevención de Actos de Corrupción'.\n\n¡Atentamente,\nUniversidad Nacional de Juliaca!")

                with open(cert_path, 'rb') as f:
                    file_data = f.read()
                    file_name = os.path.basename(cert_path)

                msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)

                with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=SMTP_TIMEOUT) as smtp:
                    smtp.login(EMAIL_REMITE, EMAIL_PASSWORD)
                    smtp.send_message(msg)

                return jsonify({"success": True, "message": f"✅ Certificado enviado a {a['email']}."})
            except Exception as e:
                return jsonify({"success": False, "message": f"Error al enviar correo (verifica red o contraseña de app): {str(e)}"})

    return jsonify({"success": False, "message": "Asistente no encontrado."})


@app.route("/api/enviar-certificados-masivos", methods=["POST"])
def enviar_certificados_masivos():
    asistentes = cargar_datos()
    enviados = 0
    errores = 0

    for a in asistentes:
        if a["asistio"]:
            try:
                cert_path, cert_url = generar_certificado_pdf(a["nombre"], a["dni"], a["escuela"], a["semestre"])
                a["certificado_url"] = cert_url

                msg = EmailMessage()
                msg['Subject'] = "🎓 Certificado - Seminario UNAJ"
                msg['From'] = EMAIL_REMITE
                msg['To'] = a["email"]

                msg.set_content(f"Estimado(a) {a['nombre']},\n\nGracias por su participación en el Seminario. Adjunto su certificado oficial en formato PDF.\n\n¡Atentamente,\nUniversidad Nacional de Juliaca!")

                with open(cert_path, 'rb') as f:
                    file_data = f.read()
                    file_name = os.path.basename(cert_path)

                msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)

                with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=SMTP_TIMEOUT) as smtp:
                    smtp.login(EMAIL_REMITE, EMAIL_PASSWORD)
                    smtp.send_message(msg)

                enviados += 1
            except Exception as e:
                errores += 1
                print(f"Error enviando a {a['email']}: {e}")

    guardar_datos(asistentes)

    if enviados == 0 and errores > 0:
        return jsonify({
            "success": False,
            "message": f"⚠️ No se pudieron enviar los {errores} correos (posible bloqueo de puerto SMTP en la red actual). Los certificados PDF están listos para descarga directa en la tabla."
        })

    return jsonify({"success": True, "message": f"✅ Se enviaron {enviados} certificados en PDF correctamente."})


@app.route("/api/exportar-csv")
def exportar_csv():
    asistentes = cargar_datos()
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["DNI / Código", "Nombre", "Correo", "Escuela / Categoría", "Semestre", "Asistió", "Hora Ingreso", "Certificado PDF"])

    base_url = request.host_url.rstrip("/")

    for a in asistentes:
        writer.writerow([
            a["dni"],
            a["nombre"],
            a["email"],
            a["escuela"],
            a["semestre"],
            "SÍ" if a["asistio"] else "NO",
            a["hora_ingreso"] if a["hora_ingreso"] else "-",
            f"{base_url}{a['certificado_url']}" if a.get("certificado_url") else "-"
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype="text/csv",
        as_attachment=True,
        download_name="reporte_seminario_unaj.csv"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
