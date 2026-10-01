fn main() {
    println!(
        "cargo:rustc-env=STUDIO_TARGET={}",
        std::env::var("TARGET").unwrap()
    );
    tauri_build::build()
}
