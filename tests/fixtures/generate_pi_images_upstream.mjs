// Development oracle. Run against the pinned upstream Photon Node package only.
import fs from "node:fs";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
const require = createRequire(import.meta.url);
const directory = process.env.PI_REFERENCE_DEPS;
if (!directory) throw new Error("PI_REFERENCE_DEPS is required");
const photon = require(`${directory}/@silvia-odwyer/photon-node`);
const cases = [];
for (const [width,height,newWidth,newHeight,kind] of [
 [1,1,1,1,"solid"],[3,2,3,2,"solid"],[100,100,100,100,"solid"],
 [5,7,3,4,"pattern"],[13,9,8,5,"pattern"],[7,5,12,9,"alpha"],
 [31,23,7,4,"noise"],[64,48,29,20,"pattern"],[101,99,51,49,"alpha"],
 [11,1,3,1,"noise"],[1,11,1,3,"noise"],
 [258,5,100,2,"solid"],[64,64,64,64,"noise"],
]) {
 let state=0x12345678;
 const pixels=Uint8Array.from({length:width*height*4},(_,i)=> {
   state=(Math.imul(state,1664525)+1013904223)>>>0;
   if(kind==="solid") return [17,64,210,255][i%4];
   if(kind==="noise") return state>>>24;
   if(i%4===3 && kind!=="alpha") return 255;
   return (Math.floor(i/4)*31+i%4*79+Math.floor(i/(width*4))*17)%256;
 });
 const image=new photon.PhotonImage(pixels,width,height);
 const resized=photon.resize(image,newWidth,newHeight,photon.SamplingFilter.Lanczos3);
 const result={name:`${kind}-${width}x${height}-${newWidth}x${newHeight}`,width,height,new_width:newWidth,new_height:newHeight,
   pixels:Buffer.from(pixels).toString("base64"),
   resized:Buffer.from(resized.get_raw_pixels()).toString("base64"),
   png:Buffer.from(resized.get_bytes()).toString("base64"),
   jpeg:Object.fromEntries([40,55,70,80,85,100].map(q=>[q,Buffer.from(resized.get_bytes_jpeg(q)).toString("base64")]))};
 cases.push(result);resized.free();image.free();
}
const result={baseline:{package:"@silvia-odwyer/photon-node",version:require(`${directory}/@silvia-odwyer/photon-node/package.json`).version,
 wasm_sha256:createHash("sha256").update(fs.readFileSync(`${directory}/@silvia-odwyer/photon-node/photon_rs_bg.wasm`)).digest("hex")},cases};
const destination=process.argv[2]||"tests/fixtures/pi_images_upstream.json";
fs.writeFileSync(destination,JSON.stringify(result,null,2)+"\n");
console.log(JSON.stringify({destination,cases:cases.length}));
