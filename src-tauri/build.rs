fn main() {
    println!("cargo:rerun-if-changed=../src/meocosub2/overlay/static");
    tauri_build::build()
}
