use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use std::error::Error;
use std::fs;
use std::io::Read;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args_os().skip(1);
    let bundle = PathBuf::from(
        args.next()
            .ok_or("Expected updater ZIP and signature paths")?,
    );
    let signature_path = PathBuf::from(args.next().ok_or("Expected signature path")?);
    if args.next().is_some() {
        return Err("Expected exactly two file paths".into());
    }
    let public_key = std::env::var("MEOWCAL_UPDATER_PUBLIC_KEY")?;
    let decoded_key = STANDARD.decode(public_key.trim())?;
    let decoded_signature = STANDARD.decode(fs::read_to_string(signature_path)?.trim())?;
    let key = PublicKey::decode(std::str::from_utf8(&decoded_key)?)?;
    let signature = Signature::decode(std::str::from_utf8(&decoded_signature)?)?;
    let mut verifier = key.verify_stream(&signature)?;
    let mut file = fs::File::open(bundle)?;
    let mut chunk = [0u8; 64 * 1024];
    loop {
        let length = file.read(&mut chunk)?;
        if length == 0 {
            break;
        }
        verifier.update(&chunk[..length]);
    }
    verifier.finalize()?;
    println!("Updater signature matches the embedded public key.");
    Ok(())
}
