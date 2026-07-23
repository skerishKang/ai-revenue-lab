document.addEventListener('click',event=>{
  const roleButton=event.target.closest('[data-role]');
  if(roleButton&&typeof closeModal==='function') closeModal();
},true);

document.addEventListener('click',event=>{
  if(event.target.closest('button')) return;
  const card=event.target.closest('[data-open]');
  if(!card) return;
  state.selected=Number(card.dataset.open);
  route('detail');
});

document.addEventListener('error',event=>{
  const image=event.target;
  if(!(image instanceof HTMLImageElement)||image.dataset.fallbackApplied) return;
  image.dataset.fallbackApplied='true';
  image.alt='합성 예시 이미지 대체 화면';
  image.src='data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600">'+
    '<rect width="100%" height="100%" fill="#e7eae7"/>'+
    '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '+
    'fill="#5f6662" font-family="sans-serif" font-size="30">합성 예시 이미지</text></svg>'
  );
},true);
