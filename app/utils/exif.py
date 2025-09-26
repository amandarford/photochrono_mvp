import subprocess, shutil, os, tempfile, textwrap


def have_exiftool() -> bool:
    return shutil.which("exiftool") is not None


def write_exif_datetime(path: str, dt: str) -> bool:
    """Write EXIF DateTimeOriginal and XMP:DateCreated via exiftool.
    dt format e.g. '1997:08:01 12:00:00'.
    """
    if not have_exiftool():
        return False
    cmd = [
        "exiftool",
        "-overwrite_original",
        f"-EXIF:DateTimeOriginal={dt}",
        f"-XMP:DateCreated={dt}",
        path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print("ExifTool error:", e.stderr.decode("utf-8", "ignore"))
        return False


def write_xmp_people_sidecar(path: str, people: list[str]) -> bool:
    """Create a minimal .xmp sidecar with PersonInImage entries."""
    xmp_path = path + ".xmp"
    persons = "".join([f"<rdf:li>{p}</rdf:li>" for p in people])
    xml = f"""<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='PhotoChrono'>
 <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
  <rdf:Description xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:MP='http://ns.microsoft.com/photo/1.2/' xmlns:xmp='http://ns.adobe.com/xap/1.0/'>
   <MP:PersonInImage>
    <rdf:Bag>
     {persons}
    </rdf:Bag>
   </MP:PersonInImage>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""
    with open(xmp_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return True
