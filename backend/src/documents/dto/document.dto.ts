import { Transform, Type } from 'class-transformer';
import { IsInt, IsOptional, IsString, IsUUID, Max, MaxLength, Min, MinLength } from 'class-validator';

const trim = ({ value }: { value: unknown }): unknown => (typeof value === 'string' ? value.trim() : value);
const lowerTrim = ({ value }: { value: unknown }): unknown => (typeof value === 'string' ? value.trim().toLowerCase() : value);

export class UpdateDocumentDto {
  @IsOptional()
  @Transform(trim)
  @IsString()
  @MinLength(1)
  @MaxLength(240)
  title?: string;

  @IsOptional()
  @IsUUID()
  folderId?: string | null;
}

export class InitUploadDto {
  @Transform(trim)
  @IsString()
  @MinLength(1)
  @MaxLength(240)
  title!: string;

  @IsOptional()
  @IsUUID()
  folderId?: string | null;

  @Transform(trim)
  @IsString()
  @MinLength(1)
  @MaxLength(255)
  originalFilename!: string;

  @Transform(lowerTrim)
  @IsString()
  @MinLength(3)
  @MaxLength(160)
  mediaType!: string;

  @Type(() => Number)
  @IsInt()
  @Min(0)
  sizeBytes!: number;
}

export class NewVersionInitUploadDto {
  @Transform(trim)
  @IsString()
  @MinLength(1)
  @MaxLength(255)
  originalFilename!: string;

  @Transform(lowerTrim)
  @IsString()
  @MinLength(3)
  @MaxLength(160)
  mediaType!: string;

  @Type(() => Number)
  @IsInt()
  @Min(0)
  sizeBytes!: number;
}

export class ListDocumentsQueryDto {
  @IsOptional()
  @IsUUID()
  folderId?: string;

  @IsOptional()
  @IsUUID()
  tagId?: string;

  @IsOptional()
  @IsUUID()
  cursor?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit = 20;
}

export class ListVersionsQueryDto {
  @IsOptional()
  @IsUUID()
  cursor?: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit = 20;
}
