import java.io.ByteArrayInputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.cert.CertificateFactory;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

class AabSignatureVerifier {
    static final int MAX_METADATA_BYTES = 16 * 1024 * 1024;
    static final int MAX_TOTAL_METADATA_BYTES = 64 * 1024 * 1024;

    public static void main(String[] args) throws Exception {
        var boundedMetadata = new HashMap<String, byte[]>();
        long metadataBytes = 0;
        try (JarFile raw = new JarFile(args[0], false)) {
            var entries = raw.entries();
            while (entries.hasMoreElements()) {
                var entry = entries.nextElement();
                if (entry.isDirectory()) {
                    try (var input = raw.getInputStream(entry)) {
                        if (entry.getSize() != 0 || input.read() != -1) {
                            System.exit(5);
                        }
                    }
                    continue;
                }
                String name = entry.getName().toUpperCase(Locale.ROOT);
                if (name.startsWith("META-INF/") && name.indexOf('/', 9) < 0) {
                    if (name.startsWith("META-INF/SIG-")) {
                        throw new SecurityException("Unverified signature metadata: " + entry.getName());
                    }
                    if (name.equals(JarFile.MANIFEST_NAME) || name.endsWith(".SF")
                            || name.endsWith(".RSA") || name.endsWith(".DSA") || name.endsWith(".EC")) {
                        if (entry.getSize() > MAX_METADATA_BYTES) {
                            System.exit(2);
                        }
                        byte[] contents = readMetadata(raw, entry);
                        metadataBytes += contents.length;
                        if (metadataBytes > MAX_TOTAL_METADATA_BYTES) {
                            System.exit(3);
                        }
                        if (boundedMetadata.put(name, contents) != null) {
                            throw new SecurityException("Ambiguous signature metadata: " + entry.getName());
                        }
                    }
                }
            }
        }
        try (JarFile jar = new JarFile(args[0], true)) {
            var metadata = new HashMap<String, JarEntry>();
            var entries = jar.entries();
            while (entries.hasMoreElements()) {
                var entry = entries.nextElement();
                String name = entry.getName().toUpperCase(Locale.ROOT);
                if (name.startsWith("META-INF/") && name.indexOf('/', 9) < 0) {
                    if (name.startsWith("META-INF/SIG-")) {
                        throw new SecurityException("Unverified signature metadata: " + entry.getName());
                    }
                    if (name.equals(JarFile.MANIFEST_NAME) || name.endsWith(".SF")
                            || name.endsWith(".RSA") || name.endsWith(".DSA") || name.endsWith(".EC")) {
                        if (entry.getSize() > MAX_METADATA_BYTES) {
                            System.exit(2);
                        }
                        if (metadata.put(name, entry) != null) {
                            throw new SecurityException("Ambiguous signature metadata: " + entry.getName());
                        }
                    }
                }
            }
            var manifest = metadata.get(JarFile.MANIFEST_NAME);
            if (manifest == null) {
                throw new SecurityException("Missing signed JAR manifest");
            }
            byte[] manifestBytes = boundedMetadata.get(JarFile.MANIFEST_NAME);
            boolean manifestCovered = false;
            var authenticated = new HashSet<String>();
            for (var item : metadata.entrySet()) {
                String name = item.getKey();
                if (!name.endsWith(".RSA") && !name.endsWith(".DSA") && !name.endsWith(".EC")) {
                    continue;
                }
                String signatureName = name.substring(0, name.lastIndexOf('.')) + ".SF";
                var signature = metadata.get(signatureName);
                if (signature == null) {
                    throw new SecurityException("Unpaired signature metadata: " + item.getValue().getName());
                }
                byte[] signatureBytes = boundedMetadata.get(signatureName);
                byte[] blockBytes = boundedMetadata.get(name);
                var container = new ByteArrayInputStream(blockBytes);
                CertificateFactory.getInstance("X.509").generateCertificates(container);
                if (container.available() != 0) {
                    throw new SecurityException("Unsigned data after signature block: " + item.getValue().getName());
                }
                Path isolated = Path.of(args[1], "signature.jar");
                try (var output = new JarOutputStream(Files.newOutputStream(isolated))) {
                    for (var entry : new JarEntry[] {manifest, item.getValue()}) {
                        output.putNextEntry(new JarEntry(entry.getName()));
                        output.write(entry == manifest ? manifestBytes : blockBytes);
                        output.closeEntry();
                    }
                }
                try (var pair = new JarFile(isolated.toFile(), true)) {
                    var signedManifest = pair.getJarEntry(manifest.getName());
                    try (var input = pair.getInputStream(signedManifest)) {
                        input.transferTo(OutputStream.nullOutputStream());
                    }
                    if (signedManifest.getCodeSigners() != null) {
                        System.exit(4);
                    }
                }
                try (var output = new JarOutputStream(Files.newOutputStream(isolated))) {
                    JarEntry[] artifacts = {manifest, signature, item.getValue()};
                    byte[][] contents = {manifestBytes, signatureBytes, blockBytes};
                    for (int i = 0; i < artifacts.length; i++) {
                        output.putNextEntry(new JarEntry(artifacts[i].getName()));
                        output.write(contents[i]);
                        output.closeEntry();
                    }
                }
                try (var pair = new JarFile(isolated.toFile(), true)) {
                    var signedManifest = pair.getJarEntry(manifest.getName());
                    try (var input = pair.getInputStream(signedManifest)) {
                        input.transferTo(OutputStream.nullOutputStream());
                    }
                    if (signedManifest.getCodeSigners() == null) {
                        throw new SecurityException("Unverified signature metadata: " + item.getValue().getName());
                    }
                }
                try (var input = new ByteArrayInputStream(signatureBytes)) {
                    for (var attribute : new Manifest(input).getMainAttributes().entrySet()) {
                        String key = attribute.getKey().toString();
                        String suffix = "-Digest-Manifest";
                        if (key.toUpperCase(Locale.ROOT).endsWith(suffix.toUpperCase(Locale.ROOT))) {
                            byte[] digest = MessageDigest.getInstance(key.substring(0, key.length() - suffix.length()))
                                    .digest(manifestBytes);
                            if (MessageDigest.isEqual(digest, Base64.getDecoder().decode(attribute.getValue().toString()))) {
                                manifestCovered = true;
                            }
                        }
                    }
                }
                authenticated.add(JarFile.MANIFEST_NAME);
                authenticated.add(signatureName);
                authenticated.add(name);
            }
            if (!authenticated.equals(metadata.keySet()) || !manifestCovered) {
                throw new SecurityException("Unverified signature metadata");
            }
            for (String name : new Manifest(new ByteArrayInputStream(manifestBytes)).getEntries().keySet()) {
                if (jar.getJarEntry(name) == null) {
                    throw new SecurityException("Missing signed AAB entry: " + name);
                }
            }
            entries = jar.entries();
            while (entries.hasMoreElements()) {
                var entry = entries.nextElement();
                if (entry.isDirectory()) {
                    if (entry.getSize() != 0) {
                        throw new SecurityException("Directory contains unsigned payload: " + entry.getName());
                    }
                    continue;
                }
                String name = entry.getName().toUpperCase(Locale.ROOT);
                if (metadata.containsKey(name) && !name.equals(JarFile.MANIFEST_NAME)) {
                    continue;
                }
                try (var input = jar.getInputStream(entry)) {
                    input.transferTo(OutputStream.nullOutputStream());
                }
                if (entry.getCodeSigners() == null) {
                    throw new SecurityException("Unsigned AAB entry: " + entry.getName());
                }
            }
        }
    }

    static byte[] readMetadata(JarFile jar, JarEntry entry) throws Exception {
        try (var input = jar.getInputStream(entry)) {
            byte[] data = input.readNBytes(MAX_METADATA_BYTES + 1);
            if (data.length > MAX_METADATA_BYTES) {
                System.exit(2);
            }
            return data;
        }
    }
}
